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

    VERSION = "medical-rules-v1"

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

    def __init__(self, classifier_version: str = VERSION) -> None:
        self.classifier_version = classifier_version

    def classify(
        self,
        parsed: dict[str, Any],
        filename: str = "",
        original_filename: str = "",
    ) -> MedicalDocumentAnalysis:
        """Return a type, confidence, and the signals that led to it."""
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
        signals = self._signals(haystack, heading_types)

        if self._is_empty(parsed, text):
            return MedicalDocumentAnalysis(
                document_kind=MedicalDocumentKind.UNKNOWN.value,
                confidence=0.0,
                language=language,
                classifier_version=self.classifier_version,
                warnings=["ocr_required"] if self._format(parsed) == "pdf" else ["no_extractable_text"],
            )

        scores = self._scores(haystack, heading_types, signals)
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
                text, self._GUIDELINE_TERMS, "found_guideline_terms"
            ),
            MedicalDocumentKind.LAB_REPORT.value: self._keyword_score(
                text, self._LAB_TERMS, "found_lab_terms"
            ),
            MedicalDocumentKind.IMAGING_REPORT.value: self._keyword_score(
                text, self._IMAGING_TERMS, "found_imaging_terms"
            ),
            MedicalDocumentKind.DISCHARGE_SUMMARY.value: self._keyword_score(
                text, self._DISCHARGE_TERMS, "found_discharge_terms"
            ),
            MedicalDocumentKind.PRESCRIPTION.value: self._keyword_score(
                text, self._PRESCRIPTION_TERMS, "found_prescription_terms"
            ),
            MedicalDocumentKind.CLINICAL_REPORT.value: self._keyword_score(
                text, self._CLINICAL_RECORD_TERMS, "found_clinical_record_terms"
            ),
            MedicalDocumentKind.PATIENT_NOTE.value: self._patient_note_score(text),
            MedicalDocumentKind.OTHER_MEDICAL.value: 0.35
            if any(
                signal in signal_set
                for signal in ("found_medical_terms", "found_japanese_medical_terms")
            )
            else 0.0,
        }

    def _signals(self, text: str, heading_types: set[str]) -> list[str]:
        signals: list[str] = []
        checks = (
            ("found_doi", self._DOI.search(text)),
            ("found_journal_metadata", self._JOURNAL_METADATA.search(text)),
            ("found_medical_terms", self._MEDICAL_TERMS.search(text) or self._MEDICAL_CJK_TERMS.search(text)),
            ("found_japanese_medical_terms", self._JAPANESE_MEDICAL_TERMS.search(text)),
            ("found_guideline_terms", self._GUIDELINE_TERMS.search(text)),
            ("found_lab_terms", self._LAB_TERMS.search(text)),
            ("found_imaging_terms", self._IMAGING_TERMS.search(text)),
            ("found_discharge_terms", self._DISCHARGE_TERMS.search(text)),
            ("found_prescription_terms", self._PRESCRIPTION_TERMS.search(text)),
            ("found_clinical_record_terms", self._CLINICAL_RECORD_TERMS.search(text)),
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

    def _keyword_score(self, text: str, pattern: re.Pattern[str], signal: str) -> float:
        if not pattern.search(text):
            return 0.0
        return 0.6 if signal == "found_guideline_terms" else 0.55

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
