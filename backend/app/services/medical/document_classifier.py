"""Rule-based classification for medical documents."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.medical.models import MedicalDocumentAnalysis, MedicalDocumentKind
from app.services.medical.section_normalizer import clean_heading, normalize_section_title


class MedicalDocumentClassifier:
    """Classify a document from small, inspectable signals."""

    VERSION = "medical-rules-v2"

    _MEDICAL_TERMS = re.compile(
        r"\b(?:patient|patients|clinical|disease|diagnos(?:is|es)|treatment|"
        r"therapy|therapeutic|trial|cohort|hospital|symptom|medicine|health|"
        r"intervention|participants?|subjects?|adverse events?)\b",
        re.I,
    )
    _MEDICAL_CJK_TERMS = re.compile(
        r"患者|临床|疾病|诊断|治疗|疗法|试验|队列|医院|症状|医学|健康|干预|受试者|不良事件",
    )
    _DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+\b", re.I)
    _JOURNAL_METADATA = re.compile(
        r"\b(?:journal|volume|vol\.?|issue|issn|doi|pmid|published)\b",
        re.I,
    )
    _GUIDELINE_TERMS = re.compile(
        r"\b(?:clinical practice guideline|guideline|consensus statement|"
        r"recommendation|expert consensus)\b|指南|共识|ガイドライン|勧告",
        re.I,
    )
    _LAB_TERMS = re.compile(
        r"\b(?:reference range|specimen|laboratory|lab result|test result|"
        r"units?|normal range)\b|参考范围|检验|化验|标本",
        re.I,
    )
    _IMAGING_TERMS = re.compile(
        r"\b(?:ct scan|mri|ultrasound|x-ray|radiology|imaging|"
        r"impression|ct)\b|影像|超声|核磁|磁共振|放射学",
        re.I,
    )
    _DISCHARGE_TERMS = re.compile(
        r"\b(?:discharge summary|discharged|hospital course|admission date)\b|"
        r"出院记录|出院小结|住院经过",
        re.I,
    )
    _PRESCRIPTION_TERMS = re.compile(
        r"\b(?:prescription|dosage|dose|frequency|take .* daily|medication list)\b|"
        r"处方|剂量|用法|用量|每日|药品",
        re.I,
    )
    _CLINICAL_RECORD_TERMS = re.compile(
        r"\b(?:medical record|clinical note|chief complaint|medical history|"
        r"patient history|physical examination)\b|病历|病史|主诉|体格检查",
        re.I,
    )
    _STRONG_CATEGORY_TERMS = {
        "found_guideline_terms": re.compile(
            r"\b(?:clinical practice guideline|evidence[- ]based guideline|"
            r"consensus statement|expert consensus|guideline development|"
            r"recommendations? for (?:patients?|treatment|management|care))\b|"
            r"指南|共识|ガイドライン|勧告",
            re.I,
        ),
        "found_lab_terms": re.compile(
            r"\b(?:laboratory report|lab report|reference range|normal range|"
            r"test result)\b|参考范围|检验|化验|标本",
            re.I,
        ),
        "found_imaging_terms": re.compile(
            r"\b(?:ct scan|mri|ultrasound|x-ray|radiology|imaging report|"
            r"imaging findings)\b|影像|超声|核磁|磁共振|放射学",
            re.I,
        ),
        "found_discharge_terms": re.compile(
            r"\b(?:discharge summary|discharged|hospital course|admission date)\b|"
            r"出院记录|出院小结|住院经过",
            re.I,
        ),
        "found_prescription_terms": re.compile(
            r"\b(?:prescription|medication list|dosage|dose|"
            r"take .* daily)\b|处方|剂量|用法|用量|每日|药品",
            re.I,
        ),
        "found_clinical_record_terms": re.compile(
            r"\b(?:medical record|clinical note|chief complaint|medical history|"
            r"patient history|physical examination)\b|病历|病史|主诉|体格检查",
            re.I,
        ),
    }
    _JAPANESE_MEDICAL_TERMS = re.compile(
        r"患者|臨床|疾患|診断|治療|療法|試験|病院|症状|医学|健康|介入|有害事象",
    )
    _RESEARCH_HEADINGS = {
        "abstract",
        "introduction",
        "methods",
        "population",
        "intervention",
        "comparator",
        "outcomes",
        "results",
        "adverse_events",
        "discussion",
        "limitations",
        "conclusion",
        "references",
    }
    _SPECIMEN_CONTEXT = re.compile(
        r"\b(?:laboratory|lab|assay|analyte|blood|urine|serum|plasma|"
        r"test result|lab result|reference range|normal range|units?)\b|"
        r"检验项目|检测结果|参考范围|单位|标本|样本",
        re.I,
    )
    _IMAGING_CONTEXT = re.compile(
        r"\b(?:ct|mri|ultrasound|x-ray|radiology|imaging|scan)\b|"
        r"影像|超声|核磁|磁共振|放射学",
        re.I,
    )
    _PRESCRIPTION_CONTEXT = re.compile(
        r"\b(?:medication|medicine|drug|prescription|tablet|capsule|"
        r"dose|dosage|administer(?:ed|ing)?|take|oral|intravenous|"
        r"injection|route|mg|mcg|milligram(?:s)?)\b|"
        r"药物|药品|剂量|给药|服用|用药|口服|注射",
        re.I,
    )
    _IMPRESSION_HEADING = re.compile(
        r"(?im)^\s*impression\s*(?::\s*\S.*)?$"
    )
    _EXPLICIT_GUIDELINE_TITLE = re.compile(
        r"\b(?:clinical practice|evidence[- ]based)\s+guidelines?\b|"
        r"\b(?:consensus statement|expert consensus)\b|指南|共识|ガイドライン",
        re.I,
    )
    _GUIDELINE_EVALUATION_TITLE = re.compile(
        r"\b(?:evaluation|evaluate|evaluating|assessment|assess(?:ed|ing)?|"
        r"impact|effect(?:iveness)?|adherence|compliance|audit|trial|"
        r"cohort|randomi[sz]ed)\b|评估|评价|效果|影响|依从性|审计",
        re.I,
    )

    def __init__(self, classifier_version: str = VERSION) -> None:
        self.classifier_version = classifier_version

    def classify(
        self,
        parsed: dict[str, Any],
        filename: str = "",
        original_filename: str = "",
    ) -> MedicalDocumentAnalysis:
        """Return a type and rule evidence; confidence is not a probability."""
        text = self._text(parsed)
        title = self._title(parsed, filename, original_filename)
        headings = self._headings(parsed)
        heading_types: set[str] = set()
        for heading in headings:
            if not heading:
                continue
            normalized = normalize_section_title(heading)
            heading_types.add(normalized.primary)
            heading_types.update(normalized.secondary)
        haystack = "\n".join(part for part in (title, text) if part)
        language = self._detect_language(haystack)
        signals = self._signals(haystack, heading_types, headings)
        if self._is_explicit_guideline_title(title):
            signals.append("found_explicit_guideline_title")

        if self._is_empty(parsed, text):
            return MedicalDocumentAnalysis(
                document_kind=MedicalDocumentKind.UNKNOWN.value,
                confidence=0.0,
                language=language,
                classifier_version=self.classifier_version,
                warnings=["ocr_required"] if self._format(parsed) == "pdf" else ["no_extractable_text"],
            )

        scores = self._scores(haystack, heading_types, signals, headings)
        if (
            self._is_explicit_guideline_title(title)
            and not self._is_guideline_evaluation_title(title)
        ):
            kind = MedicalDocumentKind.GUIDELINE.value
            score = max(scores[MedicalDocumentKind.GUIDELINE.value], 0.9)
        else:
            kind, score = max(scores.items(), key=lambda item: item[1])
        if kind == MedicalDocumentKind.RESEARCH_PAPER.value:
            enough_structure = len(heading_types & self._RESEARCH_HEADINGS) >= 2
            has_medical_signal = any(
                signal in signals
                for signal in (
                    "found_medical_terms",
                    "found_japanese_medical_terms",
                )
            )
            if not enough_structure or not has_medical_signal:
                kind = MedicalDocumentKind.UNKNOWN.value
                score = 0.0

        confidence = self._confidence(kind, score)
        return MedicalDocumentAnalysis(
            document_kind=kind,
            confidence=confidence,
            language=language,
            classifier_version=self.classifier_version,
            signals=signals,
        )

    def _scores(
        self,
        text: str,
        heading_types: set[str],
        signals: list[str],
        headings: list[str] | None = None,
    ) -> dict[str, float]:
        signal_set = set(signals)
        research_heading_count = len(heading_types & self._RESEARCH_HEADINGS)
        paper = 0.0
        paper += min(research_heading_count, 5) * 0.12
        paper += 0.25 if "found_doi" in signal_set else 0.0
        paper += 0.12 if "found_journal_metadata" in signal_set else 0.0
        paper += 0.18 if any(
            signal in signal_set
            for signal in ("found_medical_terms", "found_japanese_medical_terms")
        ) else 0.0
        paper += 0.08 if "found_abstract_heading" in signal_set else 0.0

        return {
            MedicalDocumentKind.RESEARCH_PAPER.value: min(paper, 1.0),
            MedicalDocumentKind.GUIDELINE.value: self._keyword_score(
                text, self._GUIDELINE_TERMS, "found_guideline_terms", headings
            ),
            MedicalDocumentKind.LAB_REPORT.value: self._keyword_score(
                text, self._LAB_TERMS, "found_lab_terms", headings
            ),
            MedicalDocumentKind.IMAGING_REPORT.value: self._keyword_score(
                text, self._IMAGING_TERMS, "found_imaging_terms", headings
            ),
            MedicalDocumentKind.DISCHARGE_SUMMARY.value: self._keyword_score(
                text, self._DISCHARGE_TERMS, "found_discharge_terms", headings
            ),
            MedicalDocumentKind.PRESCRIPTION.value: self._keyword_score(
                text, self._PRESCRIPTION_TERMS, "found_prescription_terms", headings
            ),
            MedicalDocumentKind.CLINICAL_REPORT.value: self._keyword_score(
                text, self._CLINICAL_RECORD_TERMS, "found_clinical_record_terms", headings
            ),
            MedicalDocumentKind.PATIENT_NOTE.value: self._patient_note_score(text),
            MedicalDocumentKind.OTHER_MEDICAL.value: 0.35
            if self._medical_context_count(text) >= 2
            else 0.0,
        }

    def _signals(
        self,
        text: str,
        heading_types: set[str],
        headings: list[str] | None = None,
    ) -> list[str]:
        signals: list[str] = []
        checks = (
            ("found_doi", self._DOI.search(text)),
            ("found_journal_metadata", self._JOURNAL_METADATA.search(text)),
            ("found_medical_terms", self._MEDICAL_TERMS.search(text) or self._MEDICAL_CJK_TERMS.search(text)),
            ("found_japanese_medical_terms", self._JAPANESE_MEDICAL_TERMS.search(text)),
            ("found_guideline_terms", self._keyword_score(
                text, self._GUIDELINE_TERMS, "found_guideline_terms", headings
            )),
            ("found_lab_terms", self._keyword_score(
                text, self._LAB_TERMS, "found_lab_terms", headings
            )),
            ("found_imaging_terms", self._keyword_score(
                text, self._IMAGING_TERMS, "found_imaging_terms", headings
            )),
            ("found_discharge_terms", self._keyword_score(
                text, self._DISCHARGE_TERMS, "found_discharge_terms", headings
            )),
            ("found_prescription_terms", self._keyword_score(
                text, self._PRESCRIPTION_TERMS, "found_prescription_terms", headings
            )),
            ("found_clinical_record_terms", self._keyword_score(
                text, self._CLINICAL_RECORD_TERMS, "found_clinical_record_terms", headings
            )),
        )
        signals.extend(name for name, matched in checks if matched)
        heading_signals = {
            "found_abstract_heading": "abstract",
            "found_methods_heading": "methods",
            "found_results_heading": "results",
            "found_discussion_heading": "discussion",
            "found_references_heading": "references",
        }
        signals.extend(
            name for name, section_type in heading_signals.items()
            if section_type in heading_types
        )
        return signals

    def _keyword_score(
        self,
        text: str,
        pattern: re.Pattern[str],
        signal: str,
        headings: list[str] | None = None,
    ) -> float:
        matched = pattern.search(text)
        imaging_heading = signal == "found_imaging_terms" and self._has_imaging_heading(
            text, headings or []
        )
        if not matched and not imaging_heading:
            return 0.0

        # These words are common in software, reviews, and ordinary prose.
        # They only count when the nearby wording looks like the document type.
        if signal == "found_lab_terms" and re.search(r"\bspecimen\b", text, re.I):
            if not self._SPECIMEN_CONTEXT.search(text):
                return 0.0
        if signal == "found_imaging_terms" and re.search(r"\bimpression\b", text, re.I):
            if not self._IMAGING_CONTEXT.search(text) and not imaging_heading:
                return 0.0
        if signal == "found_prescription_terms" and re.search(r"\bfrequency\b", text, re.I):
            if not self._PRESCRIPTION_CONTEXT.search(text):
                return 0.0

        strong_pattern = self._STRONG_CATEGORY_TERMS.get(signal)
        context_count = self._medical_context_count(text)
        if imaging_heading:
            return 0.55
        if (
            signal == "found_lab_terms"
            and re.search(r"\bspecimen\b", text, re.I)
            and self._SPECIMEN_CONTEXT.search(text)
        ):
            return 0.55
        if (
            signal == "found_prescription_terms"
            and re.search(r"\bfrequency\b", text, re.I)
            and self._PRESCRIPTION_CONTEXT.search(text)
        ):
            return 0.55
        if strong_pattern and strong_pattern.search(text):
            # A format phrase such as "reference range" is strong enough on
            # its own; guideline wording still needs a medical cue.
            if signal == "found_guideline_terms" and context_count == 0:
                return 0.0
            return 0.6 if signal == "found_guideline_terms" else 0.55
        if context_count < 2:
            return 0.0
        return 0.6 if signal == "found_guideline_terms" else 0.55

    def _has_imaging_heading(self, text: str, headings: list[str]) -> bool:
        """Accept an Impression heading, but not the same word in a sentence."""
        if any(clean_heading(heading).casefold() == "impression" for heading in headings):
            return True
        return bool(self._IMPRESSION_HEADING.search(text))

    def _is_explicit_guideline_title(self, title: str) -> bool:
        return bool(self._EXPLICIT_GUIDELINE_TITLE.search(title))

    def _is_guideline_evaluation_title(self, title: str) -> bool:
        return bool(self._GUIDELINE_EVALUATION_TITLE.search(title))

    def _medical_context_count(self, text: str) -> int:
        """Count domain cues before trusting a broad document label."""
        return (
            len(self._MEDICAL_TERMS.findall(text))
            + len(self._MEDICAL_CJK_TERMS.findall(text))
            + len(self._JAPANESE_MEDICAL_TERMS.findall(text))
        )

    def _patient_note_score(self, text: str) -> float:
        return 0.5 if re.search(r"\b(?:patient note|progress note)\b|患者记录|病人记录", text, re.I) else 0.0

    def _confidence(self, kind: str, score: float) -> float:
        if kind == MedicalDocumentKind.UNKNOWN.value:
            return round(min(0.39, max(0.1, score)), 3)
        return round(min(0.99, max(0.5, score)), 3)

    def _text(self, parsed: dict[str, Any]) -> str:
        return str(parsed.get("content") or parsed.get("raw_content") or "").strip()

    def _title(self, parsed: dict[str, Any], filename: str, original_filename: str) -> str:
        metadata = parsed.get("metadata") or {}
        return str(
            metadata.get("title")
            or parsed.get("title")
            or original_filename
            or metadata.get("original_filename")
            or Path(filename).stem
            or ""
        )

    def _headings(self, parsed: dict[str, Any]) -> list[str]:
        headings: list[str] = []
        for item in parsed.get("headers", []):
            if isinstance(item, dict) and item.get("text"):
                headings.append(str(item["text"]))
        extra = parsed.get("extra") or {}
        for item in extra.get("sections", parsed.get("sections", [])):
            if isinstance(item, dict):
                level = int(item.get("level", 0) or 0)
                title = item.get("title") or item.get("header")
                if title and level > 0 and not str(title).lower().startswith("page "):
                    headings.append(str(title))
        for item in (parsed.get("metadata") or {}).get("headings", []):
            if isinstance(item, dict) and item.get("text"):
                headings.append(str(item["text"]))

        # PDF extraction often returns a heading as a plain line instead of a
        # separate heading record. Only accept exact known headings here.
        text = self._text(parsed)
        for line in text.splitlines():
            value = line.strip()
            if not value or len(value) > 120:
                continue
            if value.startswith("#"):
                value = clean_heading(value)
            if normalize_section_title(value).primary != "unknown":
                headings.append(value)
        return headings

    def _format(self, parsed: dict[str, Any]) -> str:
        return str((parsed.get("metadata") or {}).get("format") or "").lower()

    def _is_empty(self, parsed: dict[str, Any], text: str) -> bool:
        return not text or not text.strip()

    def _detect_language(self, text: str) -> str:
        counts = Counter()
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                counts["zh"] += 1
            elif "\u3040" <= char <= "\u30ff":
                counts["ja"] += 1
            elif char.isascii() and char.isalpha():
                counts["en"] += 1
        # Japanese text can contain many kanji, so kana is the useful signal.
        if counts["ja"] >= 3:
            return "mixed" if counts["en"] >= 3 else "ja"
        active = [language for language, count in counts.items() if count >= 3]
        if len(active) > 1:
            return "mixed"
        return active[0] if active else "unknown"
