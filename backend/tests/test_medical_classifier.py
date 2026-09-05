"""Tests for the explainable medical document classifier."""

from app.services.medical.document_classifier import MedicalDocumentClassifier


def _parsed(text: str, fmt: str = "pdf", title: str = "") -> dict:
    parsed = {
        "content": text,
        "metadata": {"format": fmt},
        "extra": {"sections": []},
    }
    if title:
        parsed["title"] = title
    return parsed


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
    prescription = classifier.classify(
        _parsed("Prescription\nMedication: amoxicillin\nDose: 500 mg twice daily.")
    )
    ordinary = classifier.classify(_parsed("A short note about software modules.", fmt="txt"))

    assert guideline.document_kind == "guideline"
    assert lab.document_kind == "lab_report"
    assert imaging.document_kind == "imaging_report"
    assert prescription.document_kind == "prescription"
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


def test_common_words_need_medical_context_before_becoming_category_signals():
    classifier = MedicalDocumentClassifier()
    examples = (
        "The specimen is an example of this design pattern.",
        "The specimen is stored near the lab.",
        "这个昆虫标本很漂亮。",
        "My impression of the movie was positive.",
        "The CPU frequency is 3.5 GHz.",
        "The specimen is an example of this design pattern. Each unit has tests.",
        "The CPU frequency is configurable.\nThe software stores drug research papers.",
        "The CPU frequency is configurable\nDrug research notes are stored here.",
    )

    for text in examples:
        result = classifier.classify(_parsed(text, fmt="txt"))
        assert result.document_kind == "unknown", (text, result.to_dict())


def test_local_medical_context_still_supports_lab_and_prescription_documents():
    classifier = MedicalDocumentClassifier()

    lab = classifier.classify(
        _parsed("The specimen blood test result was 4 units within the reference range.", fmt="txt")
    )
    prescription = classifier.classify(
        _parsed("The medication frequency is twice daily at a dose of 500 mg.", fmt="txt")
    )

    assert lab.document_kind == "lab_report"
    assert prescription.document_kind == "prescription"


def test_multiline_lab_and_prescription_fields_are_kept_as_structured_blocks():
    classifier = MedicalDocumentClassifier()

    lab = classifier.classify(
        _parsed(
            """Laboratory Report
Specimen: Blood
Test: Hemoglobin
Result: 13.5 g/dL
Reference range: 12-16 g/dL""",
            fmt="txt",
        )
    )
    prescription = classifier.classify(
        _parsed(
            """Prescription
Medication: Amoxicillin
Dose: 500 mg
Route: Oral
Frequency: twice daily""",
            fmt="txt",
        )
    )

    assert lab.document_kind == "lab_report"
    assert prescription.document_kind == "prescription"


def test_published_guideline_title_wins_over_journal_paper_structure():
    text = """Abstract
Patients with disease were considered in the recommendations.

Methods
The panel reviewed clinical evidence.

Results
The evidence supported the recommendations.

Discussion
The panel discussed the strength of the evidence.

References
10.1000/example"""

    result = MedicalDocumentClassifier().classify(
        _parsed(
            text,
            title="Clinical Practice Guideline for Disease Treatment",
        )
    )

    assert result.document_kind == "guideline"
    assert "found_explicit_guideline_title" in result.signals


def test_body_guideline_title_is_used_when_upload_title_is_a_storage_hash():
    text = """Clinical Practice Guideline for Disease Treatment

Abstract
Patients with disease were considered in the recommendations.

Methods
The panel reviewed clinical evidence.

Results
The evidence supported the recommendations.

Discussion
The panel discussed the strength of the evidence.

References
10.1000/example"""

    result = MedicalDocumentClassifier().classify(
        _parsed(text, title="5911a89b06929ffe"),
        filename="/uploads/5911a89b06929ffe.pdf",
        original_filename="clinical-guideline.pdf",
    )

    assert result.document_kind == "guideline"
    assert "found_explicit_guideline_title" in result.signals


def test_guideline_evaluation_article_can_still_be_a_research_paper():
    text = """Abstract
Patients with disease were included.

Introduction
The guideline was introduced in hospitals.

Methods
We evaluated implementation across a clinical cohort.

Results
Treatment outcomes improved after implementation.

Discussion
The findings support further evaluation.

References
10.1000/example"""

    result = MedicalDocumentClassifier().classify(
        _parsed(
            text,
            title="Evaluation of a Clinical Practice Guideline for Disease Treatment",
        )
    )

    assert result.document_kind == "research_paper"


def test_guideline_phrase_in_abstract_prose_does_not_become_a_title():
    text = """Abstract
This study examines a clinical practice guideline for disease treatment.
Patients with disease were included.

Introduction
The guideline was introduced in hospitals.

Methods
We evaluated implementation across a clinical cohort.

Results
Treatment outcomes improved after implementation.

Discussion
The findings support further evaluation.

References
10.1000/example"""

    result = MedicalDocumentClassifier().classify(
        _parsed(text, title="25130c2a7c0e9b4d"),
        filename="/uploads/25130c2a7c0e9b4d.pdf",
        original_filename="guideline-study.pdf",
    )

    assert result.document_kind == "research_paper"
    assert "found_explicit_guideline_title" not in result.signals


def test_japanese_guideline_and_guideline_evaluation_paper_are_distinguished():
    text = """要旨
患者を対象とした医学研究です。

序論
疾患に対する診療方針を説明します。

方法
研究では治療の実施状況を調査しました。

結果
治療の効果を解析しました。

考察
結果を検証し、影響を評価しました。

参考文献
10.1000/example"""
    classifier = MedicalDocumentClassifier()

    guideline = classifier.classify(
        _parsed(text, title="診療ガイドライン 疾患治療")
    )
    evaluation = classifier.classify(
        _parsed(text, title="診療ガイドライン遵守率の評価研究")
    )

    assert guideline.document_kind == "guideline"
    assert evaluation.document_kind == "research_paper"


def test_japanese_research_group_in_a_guideline_title_is_not_evaluation():
    text = """要旨
患者の診療方針を示します。

方法
医学的根拠を整理しました。

結果
推奨内容をまとめました。

考察
診療での使用方法を説明します。

参考文献
10.1000/example"""

    result = MedicalDocumentClassifier().classify(
        _parsed(text, title="厚生労働省研究班 診療ガイドライン")
    )

    assert result.document_kind == "guideline"


def test_journal_name_before_body_guideline_title_is_skipped():
    text = """Journal of Rare Diseases
Jane Doe, John Smith
Clinical Practice Guideline for Disease Treatment
Abstract
Patients with disease were considered in the recommendations.

Methods
The panel reviewed clinical evidence.

Results
The evidence supported the recommendations.

Discussion
The panel discussed the strength of the evidence.

References
10.1000/example"""

    result = MedicalDocumentClassifier().classify(
        _parsed(text, title="25130c2a7c0e9b4d"),
        filename="/uploads/25130c2a7c0e9b4d.pdf",
        original_filename="clinical-guideline.pdf",
    )

    assert result.document_kind == "guideline"


def test_guideline_scope_terms_do_not_override_guideline_titles():
    text = """Abstract
Patients with disease were considered in the recommendations.

Methods
The panel reviewed clinical evidence.

Results
The evidence supported the recommendations.

Discussion
The panel discussed the strength of the evidence.

References
10.1000/example"""
    titles = (
        "Clinical Practice Guideline for Assessment and Treatment of Disease",
        "Clinical Practice Guideline for Evaluation of Treatment Effectiveness",
        "临床疗效评价指南",
        "治療効果評価ガイドライン",
        "Clinical Practice Guideline for Hospital Management of Disease",
    )

    classifier = MedicalDocumentClassifier()
    for title in titles:
        result = classifier.classify(_parsed(text, title=title))
        assert result.document_kind == "guideline", (title, result.to_dict())


def test_lab_result_fields_accept_scientific_notation_and_common_units():
    examples = (
        "Specimen: Blood\nTest: WBC\nResult: 5.2 ×10^9/L",
        "样本：血液\n检测项目：白细胞\n检测结果：5.2×10^9/L",
        "Specimen: Serum\nAnalyte: TSH\nResult: 2.1 mIU/L",
        "Specimen: Blood\nTest: WBC\nResult: 5.2",
    )

    classifier = MedicalDocumentClassifier()
    for text in examples:
        result = classifier.classify(_parsed(text, fmt="txt"))
        assert result.document_kind == "lab_report", (text, result.to_dict())


def test_keyword_pairs_without_report_structure_stay_unknown():
    classifier = MedicalDocumentClassifier()

    lab = classifier.classify(
        _parsed("This specimen module has a unit test", fmt="txt")
    )
    prescription = classifier.classify(
        _parsed(
            "The CPU frequency and medication dose are stored in the same table.",
            fmt="txt",
        )
    )

    assert lab.document_kind == "unknown"
    assert prescription.document_kind == "unknown"


def test_empty_pdf_is_marked_for_ocr_instead_of_being_guessed():
    result = MedicalDocumentClassifier().classify(_parsed("", fmt="pdf"))

    assert result.document_kind == "unknown"
    assert result.confidence == 0.0
    assert result.warnings == ["ocr_required"]
