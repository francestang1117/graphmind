"""Provider boundary for medical insight generation.

The local provider keeps development and tests deterministic. A remote model
can be added later without changing the report or citation contracts.
"""

from __future__ import annotations

import copy
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from app.services.medical.ai.context_builder import AnalysisContext, EvidenceItem
from app.services.medical.ai.exceptions import MedicalInsightError, ProviderUnavailable
from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.text_quality import assess_passage


class MedicalAIProvider(Protocol):
    name: str
    model_name: str

    def generate(self, prompt: str, context: AnalysisContext) -> Any:
        """Return a JSON-compatible report candidate."""


class ExtractiveMedicalAIProvider:
    """Create a conservative local report from selected source passages."""

    name = "extractive"

    def __init__(self, model_name: str = "extractive-v3") -> None:
        self.model_name = model_name

    def generate(self, _prompt: str, context: AnalysisContext) -> dict[str, Any]:
        evidence = context.evidence
        study_aim = _find_study_aim(evidence)
        if study_aim:
            summary, overview_item = study_aim
            summary_is_study_aim = True
        else:
            overview_item = _first_of(
                evidence,
                "abstract",
                "scope",
                "recommendations",
                "evidence",
                "results",
                "conclusion",
                "introduction",
            ) or (evidence[0] if evidence else None)
            overview_text = overview_item.text if overview_item else ""
            summary, summary_is_study_aim = _overview_summary_details(overview_text)
        if not summary:
            summary = "The document contains no extractable passage for a summary."

        finding_sections = (
            {"results", "result", "outcomes"}
            if context.document_kind == "research_paper"
            else {"results", "result", "evidence", "recommendations", "discussion"}
        )
        findings = []
        for item in _take_distinct(
            evidence,
            finding_sections,
            limit=3,
        ):
            if overview_item and item.evidence_id == overview_item.evidence_id:
                continue
            statement = _summary(item.text)
            if not statement:
                continue
            findings.append(
                _finding(
                    f"finding_{len(findings) + 1:03d}",
                    statement,
                    f"This is reported in the document's {item.section_type} section.",
                    item,
                    interpretation_type="direct_statement",
                )
            )

        authors_conclusions = []
        for item in _take_distinct(evidence, {"conclusion", "conclusions"}, limit=2):
            if overview_item and item.evidence_id == overview_item.evidence_id:
                continue
            statement = _conclusion_excerpt(item)
            if not statement:
                continue
            authors_conclusions.append(
                _finding(
                    f"conclusion_{len(authors_conclusions) + 1:03d}",
                    statement,
                    "This passage appears in the document's conclusion section.",
                    item,
                    interpretation_type="direct_statement",
                )
            )

        limitations = [
            _finding(
                f"limitation_{index:03d}",
                _summary(item.text),
                "This limitation is stated in the source document.",
                item,
                interpretation_type="direct_statement",
            )
            for index, item in enumerate(
                _take_distinct(evidence, {"limitations"}, limit=2),
                start=1,
            )
            if _summary(item.text)
        ]

        question_suggestions = []
        population_item = _population_evidence(evidence)
        if population_item:
            question_suggestions.append(
                _question_suggestion(
                    "question_001",
                    "applicability",
                    "study_population",
                    source_kind="study_methods",
                    source_id="population",
                )
            )
        limitation_item = _first_of(evidence, "limitations", "limitation")
        limitation_finding = next(
            (
                finding
                for finding in limitations
                if finding.get("evidence_ids", [None])[0]
                == (limitation_item.evidence_id if limitation_item else None)
            ),
            None,
        )
        if limitation_item:
            question_suggestions.append(
                _question_suggestion(
                    "question_002",
                    "study_limitation",
                    "study_limitation",
                    source_kind="limitations",
                    source_id=(limitation_finding or {}).get("id", ""),
                )
            )

        warnings = ["not_medical_advice", "extractive_output", *context.warnings]
        if overview_item and not summary_is_study_aim:
            warnings.append("study_aim_unavailable")
        if not findings:
            warnings.append("no_reliable_key_findings")
        return {
            "schema_version": "medical-insights-v3",
            "document_kind": context.document_kind,
            "language": context.language,
            "overview": {
                "title": context.title,
                "summary": summary,
                "study_type": _study_type(context.document_kind),
                "evidence_ids": [overview_item.evidence_id] if overview_item else [],
            },
            "study_methods": {
                **{
                    field: _method_attribute(evidence, field)
                    for field in (
                        "design",
                        "population",
                        "what_was_measured",
                        "sample_size",
                        "comparator",
                    )
                },
                # Kept empty in new reports. The old field represented a
                # study-setting classification, not a measured analyte.
                "human_animal_in_vitro": {},
            },
            "key_findings": findings,
            "authors_conclusions": authors_conclusions,
            "limitations": limitations,
            "medical_terms": [],
            # This provider is intentionally extractive. Do not place raw
            # passages under headings that imply a plain-language explanation.
            "what_it_means": [],
            "what_it_does_not_mean": [],
            "applicability": [],
            "future_research": [],
            "question_suggestions": question_suggestions[:5],
            "questions_for_professional": [],
            "coverage": _coverage(context),
            "warnings": warnings,
        }


class OpenAIMedicalAIProvider:
    """Generate a schema-constrained report with the OpenAI Responses API."""

    name = "openai"
    manages_timeout = True

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: int = 60,
        max_output_tokens: int = 5000,
        retry_count: int = 2,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key and client is None:
            raise ProviderUnavailable(
                "OpenAI is not configured for medical insights.",
                details={"provider": self.name},
            )
        if not model_name or model_name in {"extractive-v1", "extractive-v2", "extractive-v3"}:
            raise ProviderUnavailable(
                "Set MEDICAL_AI_MODEL before enabling the OpenAI provider.",
                details={"provider": self.name},
            )
        self.model_name = model_name
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_output_tokens = max(256, int(max_output_tokens))
        self.retry_count = max(0, int(retry_count))
        self._sleep = sleep
        self._client = client or self._build_client(api_key)

    def _build_client(self, api_key: str) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderUnavailable(
                "The openai package is required for the OpenAI medical provider.",
                details={"provider": self.name},
            ) from exc
        return OpenAI(
            api_key=api_key,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    def generate(self, prompt: str, _context: AnalysisContext) -> Any:
        last_error: Exception | None = None
        deadline = time.monotonic() + self.timeout_seconds
        for attempt in range(self.retry_count + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MedicalInsightError(
                    "OpenAI medical insight request timed out.",
                    code="provider_timeout",
                ) from last_error
            try:
                response = self._client.responses.create(
                    model=self.model_name,
                    input=prompt,
                    max_output_tokens=self.max_output_tokens,
                    store=False,
                    timeout=remaining,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "medical_insight_report",
                            "strict": True,
                            "schema": _strict_json_schema(
                                MedicalInsightReport.model_json_schema()
                            ),
                        }
                    },
                )
                output_text = getattr(response, "output_text", None)
                if not output_text:
                    raise MedicalInsightError(
                        "OpenAI returned no medical insight report.",
                        code="provider_empty_response",
                    )
                # Keep parsing in the analyzer so malformed output gets the
                # same single repair attempt as every other provider.
                return output_text
            except MedicalInsightError:
                raise
            except Exception as exc:
                last_error = exc
                code = _provider_error_code(exc)
                retryable = code in {"provider_timeout", "provider_rate_limited", "provider_unavailable"}
                if not retryable or attempt >= self.retry_count:
                    raise MedicalInsightError(
                        "OpenAI medical insight request failed.",
                        code=code,
                    ) from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MedicalInsightError(
                        "OpenAI medical insight request timed out.",
                        code="provider_timeout",
                    ) from exc
                self._sleep(min(2**attempt, 4, remaining))
        raise MedicalInsightError(
            "OpenAI medical insight request failed.",
            code="provider_failed",
        ) from last_error


class FakeMedicalAIProvider:
    """Test provider that returns prepared payloads without a network call."""

    name = "fake"

    def __init__(
        self,
        payload: Any | None = None,
        payloads: list[Any] | None = None,
        model_name: str = "fake-v1",
    ) -> None:
        self.model_name = model_name
        self.payload = payload
        self.payloads = list(payloads or [])
        self.calls: list[tuple[str, AnalysisContext]] = []

    def generate(self, prompt: str, context: AnalysisContext) -> Any:
        self.calls.append((prompt, context))
        if self.payloads:
            return copy.deepcopy(self.payloads.pop(0))
        if self.payload is not None:
            return copy.deepcopy(self.payload)
        return ExtractiveMedicalAIProvider().generate(prompt, context)


def get_provider(
    name: str,
    model_name: str = "",
    *,
    api_key: str | None = None,
    timeout_seconds: int | None = None,
    max_output_tokens: int | None = None,
    retry_count: int | None = None,
) -> MedicalAIProvider:
    provider_name = (name or "extractive").strip().lower()
    if provider_name == "extractive":
        return ExtractiveMedicalAIProvider(model_name or "extractive-v3")
    if provider_name == "fake":
        return FakeMedicalAIProvider(model_name=model_name or "fake-v1")
    if provider_name == "openai":
        from app.core.config import settings

        return OpenAIMedicalAIProvider(
            api_key=(
                api_key
                if api_key is not None
                else settings.MEDICAL_AI_OPENAI_API_KEY or settings.OPENAI_API_KEY
            ),
            model_name=model_name or settings.OPENAI_MODEL,
            timeout_seconds=timeout_seconds or settings.MEDICAL_AI_TIMEOUT_SECONDS,
            max_output_tokens=max_output_tokens or settings.MEDICAL_AI_MAX_OUTPUT_TOKENS,
            retry_count=(
                settings.MEDICAL_AI_PROVIDER_RETRY_COUNT
                if retry_count is None
                else retry_count
            ),
        )
    raise ProviderUnavailable(
        f"Medical AI provider '{provider_name}' is not configured.",
        details={"provider": provider_name},
    )


def _first_of(evidence: list[EvidenceItem], *section_types: str) -> EvidenceItem | None:
    for section_type in section_types:
        item = next((item for item in evidence if item.section_type == section_type), None)
        if item:
            return item
    return None


_ENGLISH_POPULATION_MARKERS = re.compile(
    r"\b(?:participant|participants|patient|patients|subject|subjects|"
    r"population|enrolled|recruited|included)\b",
    re.I,
)
_CJK_POPULATION_MARKERS = re.compile(r"病例|患者|受试者|研究人群")
_POPULATION_COUNT_EVIDENCE = re.compile(
    r"(?:\bn\s*[=:]\s*\d[\d,]*\b"
    r"|\b\d[\d,]*\s+(?:patients?|participants?|subjects?|controls?|cases?|"
    r"adults?|children|men|women|males?|females?)\b"
    r"|\b(?:enrolled|recruited|included|consisted of|comprised|measured in)\b"
    r"[^.!?。！？]{0,120}\b\d[\d,]*\b"
    r"|\d[\d,]*(?:例|名)(?:患者|受试者|对照|病例)?"
    r"|(?:患者|受试者|对照|研究人群)[^。！？]{0,40}\d[\d,]*"
    r")",
    re.I,
)
_POPULATION_GROUP_EVIDENCE = re.compile(
    r"\b(?:the|this|a)\s+(?:study|trial|cohort|population)\b"
    r"[^.!?]{0,100}\b(?:included|enrolled|recruited|consisted of|comprised)\b"
    r"[^.!?]{1,100}\b(?:patients?|participants?|subjects?|adults?|children|"
    r"controls?|men|women|males?|females?)\b",
    re.I,
)
_CJK_POPULATION_GROUP_EVIDENCE = re.compile(
    r"(?:研究人群|研究对象|研究纳入|纳入)[^。！？]{0,50}"
    r"(?:患者|受试者|对照|成人|儿童|男性|女性)"
)
_AUTHOR_METADATA_MARKERS = re.compile(
    r"\b(?:affiliation|department|correspondence|corresponding author|email|doi)\b"
    r"|作者单位|通信作者|电子邮箱|通讯地址|基金项目",
    re.I,
)
_AUTHOR_NAME = re.compile(r"\b[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?\s+[A-Z][a-z]+\b")
_ENGLISH_SUBJECT_MARKERS = re.compile(
    r"\b(?:humans?|patients?|animals?|mouse|mice|rats?|in vitro|cell lines?|tissues?)\b",
    re.I,
)
_CJK_SUBJECT_MARKERS = re.compile(
    r"患者|受试者|人类|人体|动物|小鼠|大鼠|体外|细胞系|"
    r"组织样本|组织切片|肿瘤组织|病理组织|组织培养|组织学"
)


def _population_marker_found(text: str) -> bool:
    """Match CJK population terms without Python's ASCII word-boundary rules."""
    return bool(
        _ENGLISH_POPULATION_MARKERS.search(text or "")
        or _CJK_POPULATION_MARKERS.search(text or "")
    )


def _looks_like_author_metadata(text: str) -> bool:
    """Reject title-page/name-list text before it can become population evidence."""
    value = str(text or "")
    if _AUTHOR_METADATA_MARKERS.search(value) or "@" in value:
        return True
    names = _AUTHOR_NAME.findall(value)
    return len(names) >= 2 and ("," in value or ";" in value or len(names) >= 3)


def _population_sentence_supported(text: str) -> bool:
    value = str(text or "").strip()
    if not value or _looks_like_author_metadata(value):
        return False
    return bool(
        _POPULATION_COUNT_EVIDENCE.search(value)
        or _POPULATION_GROUP_EVIDENCE.search(value)
        or _CJK_POPULATION_GROUP_EVIDENCE.search(value)
    )


def _population_evidence(evidence: list[EvidenceItem]) -> EvidenceItem | None:
    """Return only a passage that can plausibly describe study participants."""
    for item in evidence:
        if not _evidence_is_reliable(item):
            continue
        section_type = str(item.section_type or "").strip().lower()
        if section_type not in {"abstract", "population", "methods"}:
            continue
        if any(_population_sentence_supported(sentence) for sentence in _sentence_parts(item.text)):
            return item
    return None


_METHOD_MARKERS = {
    "design": re.compile(
        r"\b(?:randomi[sz]ed|cohort|cross[- ]sectional|case[- ]control|case series|observational|trial|prospective|retrospective)\b",
        re.I,
    ),
    "what_was_measured": re.compile(
        r"\b(?:measured|quantified|determined|analyzed|analysed|assessed|evaluated|tested|collected|quantification)\b|测量|定量|检测|测定|分析|评估|收集",
        re.I,
    ),
    "sample_size": re.compile(
        r"\b(?:n\s*=|sample size|participants?|patients?|subjects?|enrolled|recruited|included)\b|例|患者|受试者",
        re.I,
    ),
    "comparator": re.compile(
        r"\b(?:control(?: group)?|comparator|placebo|versus|\bvs\.?\b|untreated)\b|对照|安慰剂",
        re.I,
    ),
}

_SAMPLE_SIZE_EVIDENCE = re.compile(
    r"(?:\bn\s*[=:]\s*\d[\d,]*\b"
    r"|\b(?:sample size|enrolled|recruited|included)\b[^.!?。！？]{0,40}\b\d[\d,]*\b"
    r"|\b\d[\d,]*\s+(?:participants?|patients?|subjects?|adults?|children)\b"
    r"|\b\d[\d,]*\s+(?:classic\s+Fabry\s+men|later[- ]onset\s+Fabry\s+men|Fabry\s+women|women|men|control(?:\s+subjects?|s?))\b"
    r"|\d[\d,]*(?:例|名(?:患者|受试者)?))",
    re.I,
)
_MEASUREMENT_EVIDENCE = re.compile(
    r"\b(?:measured|quantified|determined|analyzed|analysed|assessed|"
    r"evaluated|tested|collected|quantification)\b|测量|定量|检测|测定|分析|评估|收集",
    re.I,
)
_MEASUREMENT_OBJECT = re.compile(
    r"\b(?:plasma|serum|urine|biomarker|biomarkers|concentration|activity|"
    r"expression|sample|specimen|isoform|isoforms|level|levels|outcome|"
    r"marker|markers|cells?|tissues?)\b|血浆|血清|尿液|生物标志物|"
    r"浓度|活性|表达|样本|标本|异构体|水平|指标|细胞|组织",
    re.I,
)
_DIAGNOSTIC_CONTEXT = re.compile(
    r"\b(?:diagnos(?:e|ed|is|tic)|screen(?:ed|ing)?|classif(?:y|ied|ication)|"
    r"criteria|confirm(?:ed|ation)?)\b|诊断|筛查|分类|确诊",
    re.I,
)
_COMPARATOR_EVIDENCE = re.compile(
    r"\b(?:control(?:\s+group|s)?|placebo|usual\s+care|matched\s+group|"
    r"comparison\s+group|comparator)\b|对照(?:组)?|安慰剂",
    re.I,
)


def _method_evidence(evidence: list[EvidenceItem], field: str) -> EvidenceItem | None:
    """Use only clearly labelled method passages for structured fields."""
    if field == "population":
        return _population_evidence(evidence)

    marker = _METHOD_MARKERS.get(field)
    if marker is None:
        return None
    preferred_sections = {
        "design": ("design", "methods"),
        "what_was_measured": ("methods", "population"),
        "sample_size": ("methods",),
        "comparator": ("comparator", "methods", "population", "design"),
    }.get(field, ("methods",))
    for section_type in preferred_sections:
        for item in evidence:
            if str(item.section_type or "").strip().lower() != section_type:
                continue
            if not _evidence_is_reliable(item):
                continue
            if _method_marker_found(item.text or "", field, marker):
                return item
    return None


def _method_marker_found(text: str, field: str, marker: re.Pattern[str]) -> bool:
    if field == "population":
        return any(_population_sentence_supported(sentence) for sentence in _sentence_parts(text))
    if field == "what_was_measured":
        return any(
            _measurement_sentence_supported(sentence)
            for sentence in _sentence_parts(text)
        )
    if field == "comparator":
        return bool(_COMPARATOR_EVIDENCE.search(text or ""))
    if field == "sample_size":
        return bool(_SAMPLE_SIZE_EVIDENCE.search(text or ""))
    return bool(marker.search(text or ""))


def _sentence_parts(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return []
    return [
        part.strip()
        for part in re.split(
            r"(?<=[.!?])\s+|(?<=[.!?])(?=[A-Z][a-z])|(?<=[。！？])",
            normalized,
        )
        if part.strip()
    ]


def _method_excerpt(item: EvidenceItem, field: str) -> str:
    """Return only sentences that support the selected structured field."""
    marker = _METHOD_MARKERS.get(field)
    matching = [
        sentence
        for sentence in _sentence_parts(item.text)
        if (
            _population_sentence_supported(sentence)
            if field == "population"
            else _measurement_sentence_supported(sentence)
            if field == "what_was_measured"
            else _method_marker_found(sentence, field, marker)
        )
    ]
    if field == "what_was_measured":
        return _measurement_excerpt(matching)
    if field == "population":
        return _compact_population_excerpt(matching)
    if field == "sample_size":
        return _compact_sample_size_excerpt(matching)
    if field == "comparator":
        return _compact_comparator_excerpt(matching)
    return _summary(" ".join(matching[:2])) if matching else ""


def _measurement_sentence_supported(text: str) -> bool:
    """Require an explicit measurement action and a measured object.

    A diagnostic or classification sentence can mention an assay and patients
    without saying what was measured. It must not populate the UI's
    ``What was measured`` field.
    """
    value = str(text or "").strip()
    if not value or not _MEASUREMENT_EVIDENCE.search(value):
        return False
    if not _MEASUREMENT_OBJECT.search(value):
        return False
    if _DIAGNOSTIC_CONTEXT.search(value) and not re.search(
        r"\b(?:concentration|activity|biomarker|biomarkers|isoforms?|levels?|"
        r"expression|plasma|serum|urine)\b|血浆|血清|尿液|生物标志物|浓度|活性|异构体|水平|表达",
        value,
        re.I,
    ):
        return False
    return True


_CONTROL_COUNT = re.compile(
    r"\b\d[\d,]*\s+(?:healthy\s+)?control(?:\s+subjects?|s?)\b",
    re.I,
)
_SAMPLE_GROUP_COUNT = re.compile(
    r"\b\d[\d,]*\s+(?:classic\s+Fabry\s+men|(?:later|late)[- ]onset(?:\s+Fabry)?\s+men|"
    r"Fabry\s+women|women|men|control(?:\s+subjects?|s?)|"
    r"participants?|patients?|subjects?|adults?|children)\b",
    re.I,
)


def _measurement_excerpt(sentences: list[str]) -> str:
    """Describe the measured analytes without repeating cohort details."""
    if not sentences:
        return ""
    first = sentences[0]
    if len(first) <= 220:
        return _summary(first)

    subjects: list[str] = []
    verbs: list[str] = []
    pattern = re.compile(
        r"(?P<subject>[A-Za-z][A-Za-z0-9α-]*(?:[ /(),:+-][A-Za-z0-9α-]+){1,12})\s+"
        r"(?P<verb>were|was)\s+(?P<action>measured|quantified|determined|analyzed|analysed)",
        re.I,
    )
    for sentence in sentences:
        for match in pattern.finditer(sentence):
            subject = re.sub(
                r"^(?:while|and)\s+",
                "",
                match.group("subject").strip(),
                flags=re.I,
            )
            if subject and subject not in subjects:
                subjects.append(subject)
            verbs.append(match.group("action").lower())
    if not subjects:
        return _summary(first)

    action = verbs[0] if len(set(verbs)) == 1 else "measured"
    method = ""
    method_match = re.search(r"\b(?:using|by)\s+(.+?)(?:[.!?]|$)", first, re.I)
    if method_match:
        method_text = method_match.group(1).strip().rstrip(" ,;")
        abbreviation = re.search(r"\(([A-Z][A-Z0-9/-]+)\)", method_text)
        method = f" using {abbreviation.group(1)}" if abbreviation else f" using {method_text}"
    return _summary(f"{' and '.join(subjects)} were {action}{method}.")


def _cohort_count_groups(sentences: list[str]) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    for sentence in sentences:
        parts = re.split(r"\b(?:while|whereas)\b", sentence, flags=re.I)
        for part in parts:
            counts = [match.group(0) for match in _SAMPLE_GROUP_COUNT.finditer(part)]
            if not counts:
                continue
            lowered = part.lower()
            label = (
                "Plasma"
                if "plasma" in lowered
                else "Urine"
                if "urine" in lowered or "urinary" in lowered
                else ""
            )
            groups.append((label, list(dict.fromkeys(counts))))
    return groups


def _population_group_names(sentences: list[str]) -> list[str]:
    """Extract participant group labels without repeating their counts."""
    groups: list[str] = []
    for sentence in sentences:
        for match in _SAMPLE_GROUP_COUNT.finditer(sentence):
            group = re.sub(r"^\d[\d,]*\s+", "", match.group(0)).strip()
            normalized = re.sub(r"\s+", " ", group)
            if normalized.casefold() in {"control", "controls"}:
                normalized = "control subjects"
            elif normalized.casefold() == "late-onset men":
                normalized = "late-onset Fabry men"
            if normalized and normalized.casefold() not in {
                existing.casefold() for existing in groups
            }:
                groups.append(normalized)
    return groups


def _compact_population_excerpt(sentences: list[str]) -> str:
    """Describe who was studied without duplicating sample-size numbers."""
    groups = _population_group_names(sentences)
    if not groups:
        return _summary(" ".join(sentences[:2])) if sentences else ""

    if len(groups) == 1:
        group_text = groups[0]
    elif len(groups) == 2:
        group_text = f"{groups[0]} and {groups[1]}"
    else:
        group_text = ", ".join(groups[:-1]) + f", and {groups[-1]}"

    modalities: list[str] = []
    for sentence in sentences:
        lowered = sentence.casefold()
        if "plasma" in lowered and "plasma" not in modalities:
            modalities.append("plasma")
        if ("urine" in lowered or "urinary" in lowered) and "urine" not in modalities:
            modalities.append("urine")

    if len(modalities) == 2:
        return _summary(
            f"The study included {group_text}; plasma and urine analyses were performed."
        )
    if modalities:
        return _summary(
            f"The study included {group_text}; {modalities[0]} analysis was performed."
        )
    return _summary(f"The study included {group_text}.")


def _compact_sample_size_excerpt(sentences: list[str]) -> str:
    groups = _cohort_count_groups(sentences)
    if not groups:
        return _summary(" ".join(sentences[:2])) if sentences else ""
    if all(not label for label, _counts in groups):
        return _summary(" ".join(sentences[:2]))
    parts: list[str] = []
    for label, counts in groups:
        value = "; ".join(counts)
        parts.append(f"{label}: {value}" if label else value)
    return _summary("; ".join(dict.fromkeys(parts)))


def _compact_comparator_excerpt(sentences: list[str]) -> str:
    """Keep comparator spans concise without inventing a comparison result."""
    if not sentences:
        return ""
    groups = _cohort_count_groups(sentences)
    comparator_parts: list[str] = []
    for label, counts in groups:
        controls = [value for value in counts if _CONTROL_COUNT.fullmatch(value)]
        if controls:
            value = "; ".join(controls)
            comparator_parts.append(f"{label}: {value}" if label else value)
    if comparator_parts:
        return _summary("; ".join(dict.fromkeys(comparator_parts)))

    compact: list[str] = []
    for sentence in sentences[:3]:
        counts = [match.group(0) for match in _CONTROL_COUNT.finditer(sentence)]
        if counts:
            context = ""
            lowered = sentence.lower()
            if "plasma" in lowered:
                context = "Plasma: "
            elif "urine" in lowered or "urinary" in lowered:
                context = "Urine: "
            compact.append(context + ", ".join(counts))
        elif len(sentence) <= 180:
            compact.append(sentence)
    return _summary("; ".join(dict.fromkeys(compact))) if compact else ""


def _method_attribute(evidence: list[EvidenceItem], field: str) -> dict[str, Any]:
    item = _method_evidence(evidence, field)
    if item is None or not _evidence_is_reliable(item):
        return {}
    value = _method_excerpt(item, field)
    if not value:
        return {}
    return {
        "value": value,
        "support_status": "supported",
        "evidence_ids": [item.evidence_id],
    }


def _take_distinct(
    evidence: list[EvidenceItem],
    section_types: set[str],
    *,
    limit: int,
) -> list[EvidenceItem]:
    result: list[EvidenceItem] = []
    seen: set[str] = set()
    for item in evidence:
        if item.section_type not in section_types:
            continue
        if not _evidence_is_reliable(item):
            continue
        section_title = str(item.section_title or "").strip().lower()
        if re.match(r"^(?:study\s+)?(?:objectives?|aims?)(?:\b|$)", section_title):
            continue
        statement = _summary(item.text)
        if (
            not statement
            or re.match(
                r"^(?:(?:study|research)\s+)?(?:objectives?|aims?|purposes?)\b",
                statement,
                re.I,
            )
            or statement in seen
        ):
            continue
        seen.add(statement)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _finding(
    finding_id: str,
    statement: str,
    explanation: str,
    item: EvidenceItem,
    *,
    interpretation_type: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "statement": statement,
        "plain_explanation": explanation,
        "evidence_ids": [item.evidence_id],
        "evidence_level": "reported_in_document",
        "interpretation_type": interpretation_type,
    }


def _evidence_is_reliable(item: EvidenceItem) -> bool:
    """Re-run the passage gate for older persisted chunks as a last defense."""
    if item.quality_score < 60:
        return False
    quality = assess_passage(
        item.text,
        section_type=item.section_type,
        section_title=item.section_title,
        metadata={"quality_flags": item.quality_flags},
    )
    return quality.usable and quality.score >= 60


def _question_suggestion(
    suggestion_id: str,
    category: str,
    topic: str,
    *,
    source_kind: str,
    source_id: str,
) -> dict[str, Any]:
    return {
        "id": suggestion_id,
        "question": "",
        "rationale": "",
        "category": category,
        "topic": topic,
        "source_kind": source_kind,
        "source_id": source_id,
        "evidence_ids": [],
        "interpretation_type": "inference",
    }


def _summary(text: str, max_chars: int = 360) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    if any(
        first.casefold() == second.casefold() and first != second
        for first, second in re.findall(
            r"\b([A-Za-z][A-Za-z'-]{2,})\s+([A-Za-z][A-Za-z'-]{2,})\b",
            normalized,
        )
    ):
        return ""
    if re.search(r"\b[A-Za-z]{2,}-\s+[a-z]{2,}\b", normalized):
        return ""
    if re.match(r"^\d{1,3}[a-z]?\.\s", normalized, re.I):
        return ""
    if re.search(r"(?:^|\s)\d{3,5}$", normalized):
        return ""
    if re.search(
        r"\b(?:figure|fig\.?|table)\s+\d+\b|\b(?:the\s+)?results\s+\d{3,5}$",
        normalized,
        re.I,
    ):
        return ""
    # A fixed-size parser chunk can begin with the tail of a word or contain
    # a column/header splice. Such text is not safe to present as a finding.
    if re.match(r"^[a-z]{2,}(?:\s|,)", normalized) or re.search(
        r"\b[a-z]{2,}-\s+[A-Z][a-z]+", normalized
    ):
        return ""
    match = re.search(r"[.!?。！？](?:\s|$)", normalized)
    if match and match.end() <= max_chars:
        return normalized[: match.end()].strip()
    if len(normalized) <= max_chars:
        return normalized
    shortened = normalized[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{shortened}..."


_STUDY_AIM_SECTIONS = frozenset(
    {"abstract", "scope", "objective", "objectives", "aim"}
)
_STUDY_AIM_PATTERN = re.compile(
    r"\b(?:the present|this|our)\s+study\s+"
    r"(?:determined|examined|investigated|evaluated|assessed|quantified|aimed\s+to)\b|"
    r"\bin the present study,?\s+we\s+"
    r"(?:determined|examined|investigated|evaluated|assessed|quantified)\b|"
    r"\b(?:this\s+study|we)\s+"
    r"(?:determined|examined|investigated|evaluated|assessed|quantified|aimed\s+to)\b|"
    r"\b(?:objective|purpose|aim)\s*(?:was|is|:)\s*",
    re.I,
)


def _find_study_aim(evidence: list[EvidenceItem]) -> tuple[str, EvidenceItem] | None:
    """Find a reliable objective sentence across all abstract-like chunks."""
    for item in evidence:
        section_type = str(item.section_type or "").strip().lower()
        if section_type not in _STUDY_AIM_SECTIONS or not _evidence_is_reliable(item):
            continue
        for sentence in _sentence_parts(item.text):
            if not _STUDY_AIM_PATTERN.search(sentence):
                continue
            summary = _summary(sentence)
            if summary:
                return summary, item
    return None


def _conclusion_excerpt(item: EvidenceItem) -> str:
    """Keep two complete conclusion sentences when the passage supports them."""
    sentences = _sentence_parts(item.text)
    if not sentences:
        return ""

    first = _summary(sentences[0], max_chars=720)
    if not first or not _ends_with_sentence(first):
        return ""
    if len(sentences) < 2:
        return first

    second = _summary(sentences[1], max_chars=720)
    if not second or not _ends_with_sentence(second):
        return first

    combined = f"{first} {second}"
    quality = assess_passage(
        combined,
        section_type=item.section_type,
        section_title=item.section_title,
        metadata={"quality_flags": item.quality_flags},
    )
    if not quality.usable or quality.score < 60:
        return first
    return combined


def _ends_with_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?。！？](?:['\"”’)\]]*)?$", text.strip()))


def _overview_summary(text: str) -> str:
    return _overview_summary_details(text)[0]


def _overview_summary_details(text: str) -> tuple[str, bool]:
    normalized = " ".join(str(text or "").split()).strip()
    normalized = re.sub(
        r"^(?:objectives?|background|aims?|purpose|methods|results|conclusions?)\s*[:\-–]?\s+",
        "",
        normalized,
        flags=re.I,
    )
    sentences = _sentence_parts(normalized)
    preferred = next((sentence for sentence in sentences if _STUDY_AIM_PATTERN.search(sentence)), None)
    return (
        _summary(preferred or (sentences[0] if sentences else normalized)),
        preferred is not None,
    )


def _study_type(document_kind: str) -> str:
    return {
        "research_paper": "Research paper",
        "guideline": "Clinical guideline or consensus document",
    }.get(document_kind, "Medical document")


def _coverage(context: AnalysisContext) -> dict[str, Any]:
    return {
        "complete": context.coverage_complete,
        "selected_chunks": len(context.evidence),
        "total_chunks": context.total_chunks,
        "source_chunks_total": context.source_chunks_total,
        "eligible_chunks": context.eligible_chunks,
        "quality_filtered_chunks": context.quality_filtered_chunks,
        "scope_excluded_chunks": context.scope_excluded_chunks,
        "duplicate_chunks": context.duplicate_chunks,
        "budget_excluded_chunks": context.budget_excluded_chunks,
        "selected_tokens": sum(item.token_count for item in context.evidence),
        "max_input_tokens": context.max_input_tokens,
        "included_sections": context.included_sections,
        "omitted_sections": context.omitted_sections,
    }


def _provider_error_code(exc: Exception) -> str:
    name = exc.__class__.__name__.lower()
    status_code = getattr(exc, "status_code", None)
    if "timeout" in name or isinstance(exc, TimeoutError):
        return "provider_timeout"
    if status_code == 429 or "ratelimit" in name or "rate_limit" in name:
        return "provider_rate_limited"
    if isinstance(status_code, int) and status_code >= 500:
        return "provider_unavailable"
    return "provider_failed"


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make Pydantic's schema satisfy Structured Outputs strict mode."""
    schema = copy.deepcopy(schema)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                value["required"] = list(properties)
                value["additionalProperties"] = False
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema
