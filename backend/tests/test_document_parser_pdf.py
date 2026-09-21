"""PDF parser tests."""

import sys
from types import SimpleNamespace

from app.services.document_parser import (
    PDFParser,
    PDF_TEXT_PARSER_VERSION,
    _reconstruct_pdf_words,
    _normalise_pdf_text,
)


class FakePDF:
    def __init__(self, pages, metadata=None):
        self.pages = pages
        self.metadata = metadata or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakePDFPage:
    def __init__(self, text, tables=None, words=None, objects=False):
        self._text = text
        self._tables = tables or []
        self._words = words or []
        self.chars = [{"text": "image-backed"}] if objects else []

    def extract_text(self, **_kwargs):
        return self._text

    def extract_tables(self):
        return self._tables

    def extract_words(self, extra_attrs=None, **_kwargs):
        return self._words


def test_pdf_text_cleanup_preserves_line_ending_medical_hyphens():
    text = _normalise_pdf_text("non-\nsmall-cell lung cancer\nrandom-\nized trial")

    assert "non-\nsmall-cell" in text
    assert "random-\nized" in text
    assert "nonsmall-cell" not in text


def test_pdf_word_reconstruction_keeps_obvious_columns_in_reading_order():
    page = FakePDFPage(
        "",
        words=[
            {"text": "Left", "x0": 20, "top": 10},
            {"text": "column", "x0": 55, "top": 10},
            {"text": "Right", "x0": 330, "top": 10},
            {"text": "column", "x0": 370, "top": 10},
        ],
    )
    page.width = 600

    reconstructed = _reconstruct_pdf_words(page)

    assert reconstructed == "Left column\nRight column"
    assert "Left column Right column" not in reconstructed


def test_pdfplumber_parser_extracts_pages_and_tables(tmp_path, monkeypatch):
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    page = FakePDFPage(
        "Revenue report\nTotal revenue increased.",
        tables=[
            [
                ["Metric", "Value"],
                ["Revenue", "$10"],
                ["", ""],
            ]
        ],
        words=[
            {"text": "Revenue", "size": 18},
            {"text": "report", "size": 18},
            {"text": "Total", "size": 10},
        ],
    )

    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.metadata["parser"] == "pdfplumber"
    assert parsed.metadata["parser_version"] == PDF_TEXT_PARSER_VERSION
    assert parsed.metadata["pages"] == 1
    assert parsed.metadata["table_count"] == 1
    assert parsed.sections[0].title == "Page 1"
    assert parsed.tables[0].headers == ["Metric", "Value"]
    assert parsed.tables[0].rows == [["Revenue", "$10"]]
    assert any(chunk["type"] == "page" and chunk["page"] == 1 for chunk in parsed.chunks)
    assert any(chunk["type"] == "table" and "Revenue | $10" in chunk["text"] for chunk in parsed.chunks)


def test_pdf_table_normalizer_skips_empty_tables():
    parser = PDFParser()

    assert parser._normalise_table([]) == ([], [])
    assert parser._normalise_table([["", ""], ["", None]]) == ([], [])


def test_pdfplumber_parser_preserves_pdf_metadata_title(tmp_path, monkeypatch):
    pdf_path = tmp_path / "stored-hash.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    page = FakePDFPage("Abstract\nPatients were included.")

    fake_pdfplumber = SimpleNamespace(
        open=lambda _path: FakePDF([page], {"Title": "Clinical Practice Guideline"})
    )
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.title == "Clinical Practice Guideline"
    assert parsed.metadata["title"] == "Clinical Practice Guideline"


def test_pdfplumber_parser_reconstructs_glued_words_before_chunking(tmp_path, monkeypatch):
    pdf_path = tmp_path / "glued.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    page = FakePDFPage(
        "Patientsselectionandgeneralcharacteristics"
        " Atotalof1040patientswerereferredtotheclinic.",
        words=[
            {"text": "Patients", "x0": 10, "top": 10},
            {"text": "selection", "x0": 58, "top": 10},
            {"text": "and", "x0": 112, "top": 10},
            {"text": "general", "x0": 140, "top": 10},
            {"text": "characteristics", "x0": 188, "top": 10},
            {"text": "A", "x0": 10, "top": 24},
            {"text": "total", "x0": 22, "top": 24},
            {"text": "of", "x0": 52, "top": 24},
            {"text": "1040", "x0": 67, "top": 24},
            {"text": "patients", "x0": 98, "top": 24},
            {"text": "were", "x0": 145, "top": 24},
            {"text": "referred", "x0": 180, "top": 24},
            {"text": "to", "x0": 230, "top": 24},
            {"text": "the", "x0": 248, "top": 24},
            {"text": "clinic.", "x0": 270, "top": 24},
        ],
    )
    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert "Patients selection and general characteristics" in parsed.raw_text
    assert "A total of 1040 patients were referred to the clinic." in parsed.raw_text
    assert parsed.metadata["text_quality"] == "degraded"
    assert parsed.metadata["reconstructed_pages"] == [1]
    assert any("Patients selection" in chunk["text"] for chunk in parsed.chunks)


def test_pdf_parser_prefers_more_spaced_candidate_when_scores_tie(tmp_path, monkeypatch):
    pdf_path = tmp_path / "candidate-tie.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    class CandidatePage(FakePDFPage):
        def extract_text(self, x_tolerance=1.5, **_kwargs):
            if x_tolerance == 1.5:
                return "Thepatient was enrolled in the study."
            return "The patient was enrolled in the study."

    page = CandidatePage("")
    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.raw_text == "The patient was enrolled in the study."


def test_pdfplumber_parser_keeps_normal_long_medical_terms_readable(tmp_path, monkeypatch):
    pdf_path = tmp_path / "technical-term.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    page = FakePDFPage(
        "Globotriaosylsphingosine was measured in patients with Fabry disease. "
        "The investigators compared the biomarker with a clinical outcome."
    )
    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.metadata["text_quality"] == "good"
    assert parsed.metadata["unreadable_pages"] == []


def test_pdfplumber_parser_marks_image_only_page_unreadable(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    page = FakePDFPage("", objects=True)
    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.metadata["text_quality"] == "unreadable"
    assert parsed.metadata["unreadable_pages"] == [1]
    assert "pdf_text_unreadable_page_1" in parsed.metadata["extraction_warnings"]
