"""Tests for the explainable medical document classifier."""

from app.services.medical.document_classifier import MedicalDocumentClassifier


def _parsed(text: str, fmt: str = "pdf") -> dict:
    return {
        "content": text,
        "metadata": {"format": fmt},
        "extra": {"sections": []},
    }


def test_classifies_an_english_research_paper_from_safe_signals():
    text = """A randomized clinical study

Abstract
Patients with disease received the intervention.

Introduction
The disease remains a health concern.

Methods
We enrolled participants in a clinical trial.

Results
The treatment improved the primary outcome.

Discussion
The findings may explain the observed effect.

References
10.1000/example"""

    result = MedicalDocumentClassifier().classify(
        _parsed(text), original_filename="study.pdf"
    )

    assert result.document_kind == "research_paper"
    assert result.language == "en"
    assert result.confidence > 0.5
    assert "found_abstract_heading" in result.signals
    assert "found_methods_heading" in result.signals
    assert "found_results_heading" in result.signals
    assert "found_doi" in result.signals
    assert all("patient" not in signal for signal in result.signals)


def test_finds_pdf_headings_when_the_generic_parser_only_kept_page_blocks():
    text = """Abstract
Patients with disease were included.

Methods
The clinical study enrolled participants.

Results
The treatment changed the outcome."""
    parsed = _parsed(text)
    parsed["extra"]["sections"] = [
        {"title": "Page 1", "level": 0, "content": text}
    ]

    result = MedicalDocumentClassifier().classify(parsed)

    assert result.document_kind == "research_paper"
    assert "found_abstract_heading" in result.signals
    assert "found_methods_heading" in result.signals
    assert "found_results_heading" in result.signals


def test_classifies_chinese_and_japanese_papers():
    chinese = """摘要
患者接受治疗并完成研究。

引言
疾病会影响健康。

方法
研究纳入受试者。

结果
治疗改善结局。

讨论
结果需要进一步解释。

结论
研究支持后续试验。"""
    japanese = """医学研究

要旨
患者を対象とした研究です。

序論
疾患と健康について説明します。

方法
研究では治療を評価しました。

結果
治療の結果を報告します。

考察
結果を解釈します。

結論
今後の研究が必要です。"""

    classifier = MedicalDocumentClassifier()
    chinese_result = classifier.classify(_parsed(chinese))
    japanese_result = classifier.classify(_parsed(japanese))

    assert chinese_result.document_kind == "research_paper"
    assert chinese_result.language == "zh"
    assert japanese_result.document_kind == "research_paper"
    assert japanese_result.language == "ja"


def test_classifies_other_medical_documents_without_calling_them_papers():
    classifier = MedicalDocumentClassifier()

    guideline = classifier.classify(_parsed("Clinical practice guideline and recommendations."))
    lab = classifier.classify(_parsed("Laboratory report. Reference range: 4 to 8."))
    imaging = classifier.classify(_parsed("MRI report. Impression: no acute finding."))
    ordinary = classifier.classify(_parsed("A short note about software modules.", fmt="txt"))

    assert guideline.document_kind == "guideline"
    assert lab.document_kind == "lab_report"
    assert imaging.document_kind == "imaging_report"
    assert ordinary.document_kind == "unknown"


def test_generic_research_language_does_not_make_a_document_medical():
    result = MedicalDocumentClassifier().classify(
        _parsed("研究团队讨论软件项目的设计和实现。", fmt="txt")
    )

    assert result.document_kind == "unknown"


def test_weak_category_words_do_not_classify_ordinary_documents():
    classifier = MedicalDocumentClassifier()

    lab = classifier.classify(
        _parsed("The service has 3 units and 2 integration tests.", fmt="txt")
    )
    guideline = classifier.classify(
        _parsed("A recommendation for software architecture.", fmt="txt")
    )

    assert lab.document_kind == "unknown"
    assert guideline.document_kind == "unknown"


def test_empty_pdf_is_marked_for_ocr_instead_of_being_guessed():
    result = MedicalDocumentClassifier().classify(_parsed("", fmt="pdf"))

    assert result.document_kind == "unknown"
    assert result.confidence == 0.0
    assert result.warnings == ["ocr_required"]
