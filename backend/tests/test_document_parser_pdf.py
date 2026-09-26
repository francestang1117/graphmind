"""PDF parser tests."""

import sys
from types import SimpleNamespace

import pytest

from app.services.document_parser import (
    PDFParser,
    PDF_TEXT_PARSER_VERSION,
    _pdf_candidate_rank,
    _pdf_extract_blocks,
    _pdf_line_kind,
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

    assert "non-small-cell" in text
    assert "randomized trial" in text
    assert "nonsmall-cell" not in text


def test_pdf_text_cleanup_repairs_known_line_breaks_and_keeps_compounds():
    text = _normalise_pdf_text(
        "informa- tion at- tenuation per- formed α- Gal later- onset"
    )

    assert text == "information attenuation performed α-Gal later-onset"


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


def test_pdf_word_reconstruction_keeps_full_width_header_before_columns():
    page = FakePDFPage(
        "",
        words=[
            {"text": "Full", "x0": 20, "x1": 45, "top": 10},
            {"text": "width", "x0": 50, "x1": 80, "top": 10},
            {"text": "title", "x0": 85, "x1": 115, "top": 10},
            {"text": "here", "x0": 120, "x1": 150, "top": 10},
            {"text": "Left", "x0": 20, "x1": 42, "top": 50},
            {"text": "body", "x0": 48, "x1": 75, "top": 50},
            {"text": "Right", "x0": 330, "x1": 360, "top": 50},
            {"text": "body", "x0": 366, "x1": 393, "top": 50},
            {"text": "continues", "x0": 20, "x1": 75, "top": 65},
            {"text": "continues", "x0": 330, "x1": 385, "top": 65},
        ],
    )
    page.width = 600

    reconstructed = _reconstruct_pdf_words(page)

    assert reconstructed == "Full width title here\nLeft body\ncontinues\nRight body\ncontinues"


def test_pdf_parser_forces_coordinate_order_for_normal_spaced_two_columns(tmp_path, monkeypatch):
    pdf_path = tmp_path / "normal-columns.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    class InterleavedPage(FakePDFPage):
        def extract_text(self, **_kwargs):
            return "Left one Right one\nLeft two Right two"

    page = InterleavedPage(
        "",
        words=[
            {"text": "Left", "x0": 20, "x1": 45, "top": 20},
            {"text": "one", "x0": 50, "x1": 70, "top": 20},
            {"text": "Right", "x0": 330, "x1": 360, "top": 20},
            {"text": "one", "x0": 365, "x1": 385, "top": 20},
            {"text": "Left", "x0": 20, "x1": 45, "top": 35},
            {"text": "two", "x0": 50, "x1": 70, "top": 35},
            {"text": "Right", "x0": 330, "x1": 360, "top": 35},
            {"text": "two", "x0": 365, "x1": 385, "top": 35},
        ],
    )
    page.width = 600
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: FakePDF([page])))

    parsed = PDFParser().parse(pdf_path)

    assert parsed.raw_text == "Left one\nLeft two\nRight one\nRight two"
    assert parsed.metadata["extraction_method"] == "pdfplumber-coordinate-columns"
    assert parsed.metadata["page_layouts"][0]["mode"] == "columns"
    assert parsed.metadata["page_layouts"][0]["column_boundary"] is not None


def test_pdf_parser_detects_narrow_repeated_gutter_in_realistic_journal_layout(tmp_path, monkeypatch):
    pdf_path = tmp_path / "narrow-gutter.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    words = []
    for index in range(5):
        top = 40 + index * 14
        words.extend(
            [
                {"text": "Left", "x0": 44, "x1": 72, "top": top},
                {"text": "column", "x0": 80, "x1": 120, "top": top},
                {"text": "tail", "x0": 250, "x1": 291, "top": top},
                {"text": "Right", "x0": 303, "x1": 335, "top": top},
                {"text": "column", "x0": 343, "x1": 385, "top": top},
            ]
        )

    class InterleavedNarrowPage(FakePDFPage):
        def extract_text(self, **_kwargs):
            return "\n".join(
                f"Left column tail Right column"
                for _ in range(5)
            )

    page = InterleavedNarrowPage("", words=words)
    page.width = 595
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: FakePDF([page])))

    parsed = PDFParser().parse(pdf_path)

    assert parsed.metadata["page_layouts"][0]["mode"] == "columns"
    assert parsed.raw_text == (
        "Left column tail\n" * 5
        + "Right column\n" * 5
    ).rstrip()


def test_pdf_coordinate_reconstruction_repairs_only_safe_line_break_hyphens():
    page = FakePDFPage(
        "",
        words=[
            {"text": "anti-drug", "x0": 20, "top": 10},
            {"text": "LC-MS/MS", "x0": 90, "top": 10},
            {"text": "signifi-", "x0": 20, "top": 25},
            {"text": "cance", "x0": 20, "top": 40},
            {"text": "10–20", "x0": 90, "top": 40},
        ],
    )

    reconstructed = _reconstruct_pdf_words(page)

    assert "anti-drug" in reconstructed
    assert "LC-MS/MS" in reconstructed
    assert "significance" in reconstructed
    assert "10–20" in reconstructed
    assert "signifi-cance" not in reconstructed


def test_pdf_coordinate_reconstruction_preserves_scientific_compound_hyphens():
    page = FakePDFPage(
        "",
        words=[
            {"text": "non-", "x0": 20, "top": 10},
            {"text": "small-cell", "x0": 20, "top": 25},
            {"text": "later-", "x0": 20, "top": 40},
            {"text": "onset", "x0": 20, "top": 55},
            {"text": "informa-", "x0": 20, "top": 70},
            {"text": "tion", "x0": 20, "top": 85},
        ],
    )

    reconstructed = _reconstruct_pdf_words(page)

    assert "non-small-cell" in reconstructed
    assert "later-onset" in reconstructed
    assert "information" in reconstructed
    assert "nonsmall-cell" not in reconstructed


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


def test_pdf_parser_records_filterable_page_blocks_without_copying_source_text(
    tmp_path, monkeypatch
):
    pdf_path = tmp_path / "blocks.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    page = FakePDFPage(
        "Results\nClean result sentence.\nFigure 1. Study flow\n2",
        words=[
            {"text": "Results", "x0": 48, "x1": 85, "top": 30, "bottom": 40},
            {"text": "Clean", "x0": 48, "x1": 78, "top": 55, "bottom": 65},
            {"text": "result", "x0": 84, "x1": 116, "top": 55, "bottom": 65},
            {"text": "sentence.", "x0": 122, "x1": 176, "top": 55, "bottom": 65},
            {"text": "Figure", "x0": 48, "x1": 84, "top": 90, "bottom": 100},
            {"text": "1.", "x0": 90, "x1": 100, "top": 90, "bottom": 100},
            {"text": "Study", "x0": 106, "x1": 138, "top": 90, "bottom": 100},
            {"text": "flow", "x0": 144, "x1": 168, "top": 90, "bottom": 100},
            {"text": "2", "x0": 300, "x1": 306, "top": 760, "bottom": 770},
        ],
    )
    page.width = 612
    page.height = 792
    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: FakePDF([page])))

    parsed = PDFParser().parse(pdf_path)

    blocks = parsed.metadata["pdf_blocks"]
    kinds = [block["kind"] for block in blocks]
    assert "heading" in kinds
    assert "figure_caption" in kinds
    assert "footer" in kinds
    assert any(block["kind"] == "body" and block["medical_evidence"] for block in blocks)
    assert all("text" not in block for block in blocks)
    assert all(block["char_end"] > block["char_start"] for block in blocks)


def test_pdf_caption_does_not_absorb_body_after_a_visual_gap():
    page = FakePDFPage(
        "",
        words=[
            {"text": "Figure", "x0": 40, "x1": 80, "top": 100, "bottom": 110},
            {"text": "2.", "x0": 85, "x1": 95, "top": 100, "bottom": 110},
            {"text": "Study", "x0": 100, "x1": 130, "top": 100, "bottom": 110},
            {"text": "flow", "x0": 135, "x1": 160, "top": 100, "bottom": 110},
            {"text": "The", "x0": 40, "x1": 58, "top": 116, "bottom": 126},
            {"text": "graph", "x0": 63, "x1": 93, "top": 116, "bottom": 126},
            {"text": "shows", "x0": 98, "x1": 135, "top": 116, "bottom": 126},
            {"text": "results.", "x0": 140, "x1": 190, "top": 116, "bottom": 126},
            {"text": "The", "x0": 40, "x1": 58, "top": 160, "bottom": 170},
            {"text": "study", "x0": 63, "x1": 95, "top": 160, "bottom": 170},
            {"text": "found", "x0": 100, "x1": 135, "top": 160, "bottom": 170},
            {"text": "an", "x0": 140, "x1": 155, "top": 160, "bottom": 170},
            {"text": "effect.", "x0": 160, "x1": 205, "top": 160, "bottom": 170},
        ],
    )
    page.width = 612
    page.height = 792

    blocks, _rendered = _pdf_extract_blocks(page, page_number=1)

    assert [block["kind"] for block in blocks] == ["figure_caption", "body"]
    assert "The study found an effect." in blocks[-1]["text"]
    assert "The study found an effect." not in blocks[0]["text"]


def test_pdf_block_offsets_match_normalized_reconstructed_text():
    page = FakePDFPage(
        "",
        words=[
            {"text": "Figure", "x0": 40, "x1": 80, "top": 100, "bottom": 110},
            {"text": "1.", "x0": 85, "x1": 95, "top": 100, "bottom": 110},
            {"text": "Caption", "x0": 100, "x1": 145, "top": 100, "bottom": 110},
            {"text": "informa-", "x0": 40, "x1": 85, "top": 150, "bottom": 160},
            {"text": "tion", "x0": 40, "x1": 75, "top": 165, "bottom": 175},
            {"text": "reported.", "x0": 80, "x1": 135, "top": 165, "bottom": 175},
            {"text": "2", "x0": 300, "x1": 306, "top": 760, "bottom": 770},
        ],
    )
    page.width = 612
    page.height = 792

    blocks, rendered = _pdf_extract_blocks(page, page_number=1)

    assert "information reported." in rendered
    for block in blocks:
        assert rendered[block["char_start"] : block["char_end"]] == block["text"]


@pytest.mark.parametrize("page_label", ["Page 2", "2/8", "2"])
def test_pdf_blocks_classify_page_labels_as_footer(page_label):
    assert _pdf_line_kind({"text": page_label}) == "footer"


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


def test_pdf_parser_prefers_conservative_candidate_over_fragmented_words(tmp_path, monkeypatch):
    pdf_path = tmp_path / "candidate-fragmented.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    class CandidatePage(FakePDFPage):
        def extract_text(self, x_tolerance=1.5, **_kwargs):
            if x_tolerance == 1.5:
                return "The patient was enrolled in the study and participants were monitored during follow-up."
            return "T he patient was enrolled in the study and participants were monitored during follow-up."

    page = CandidatePage("")
    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.raw_text.startswith("The patient was enrolled")
    assert "T he patient" not in parsed.raw_text


@pytest.mark.parametrize(
    ("glued", "expected"),
    [
        ("The pvalue was significant.", "The p value was significant."),
        ("Tcell responses were measured.", "T cell responses were measured."),
        ("npatients were enrolled.", "n patients were enrolled."),
        ("Bcell activation was measured.", "B cell activation was measured."),
        ("Rvalue was reported.", "R value was reported."),
        ("xaxis labels were visible.", "x axis labels were visible."),
        ("Thelper cells were measured.", "T helper cells were measured."),
        ("Blymphocyte counts increased.", "B lymphocyte counts increased."),
        ("ncontrols were enrolled.", "n controls were enrolled."),
        ("The pthreshold was prespecified.", "The p threshold was prespecified."),
        ("The xaxes were labelled.", "The x axes were labelled."),
        ("P atients were enrolled.", "Patients were enrolled."),
        ("n ot reported.", "not reported."),
        ("r eceived treatment.", "received treatment."),
    ],
)
def test_pdf_parser_preserves_scientific_single_letter_terms(
    tmp_path, monkeypatch, glued, expected
):
    pdf_path = tmp_path / "single-letter-term.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    class CandidatePage(FakePDFPage):
        def extract_text(self, x_tolerance=1.5, **_kwargs):
            return glued if x_tolerance == 1.5 else expected

    page = CandidatePage("")
    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.raw_text == expected


@pytest.mark.parametrize(
    ("correct", "fragmented"),
    [
        ("Treatment response improved.", "T reatment response improved."),
        ("Results were significant.", "R esults were significant."),
        ("Baseline characteristics were similar.", "B aseline characteristics were similar."),
        ("Follow-up lasted 12 weeks.", "F ollow-up lasted 12 weeks."),
        ("Randomized patients received placebo.", "R andomized patients received placebo."),
        ("Population characteristics were reported.", "P opulation characteristics were reported."),
    ],
)
def test_pdf_parser_rejects_fragmented_common_words(tmp_path, monkeypatch, correct, fragmented):
    pdf_path = tmp_path / "fragmented-common-word.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    class CandidatePage(FakePDFPage):
        def extract_text(self, x_tolerance=1.5, **_kwargs):
            return correct if x_tolerance == 1.5 else fragmented

    page = CandidatePage("")
    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parsed = PDFParser().parse(pdf_path)

    assert parsed.raw_text == correct


def test_pdf_candidate_rank_does_not_treat_within_or_into_as_glued_words():
    text = "The study was conducted within the clinic and into the follow-up phase for patients."

    assert _pdf_candidate_rank(text)[1] == 0


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
