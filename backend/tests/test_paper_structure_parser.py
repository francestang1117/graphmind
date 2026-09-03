"""Tests for paper sections, page ranges, and traceable chunks."""

from app.services.medical.models import MedicalDocumentAnalysis
from app.services.medical.paper_structure_parser import PaperStructureParser


def _analysis(language: str = "en") -> MedicalDocumentAnalysis:
    return MedicalDocumentAnalysis(
        document_kind="research_paper",
        confidence=0.9,
        language=language,
        classifier_version="medical-rules-v1",
    )


def _paged_paper() -> tuple[str, dict]:
    pages = [
        "Paper title\n\nAbstract\nPatients received treatment.\n\n"
        "Introduction\nThe disease affects health.\n\nMethods\n"
        "We enrolled participants.",
        "Results\nTreatment improved outcomes.\n\nDiscussion\n"
        "The authors interpret the result.",
        "Conclusion\nThe study supports further research.\n\n"
        "References\nA cited paper.",
    ]
    text = "\n\n".join(pages)
    parsed = {
        "content": text,
        "metadata": {"format": "pdf"},
        "extra": {
            "sections": [
                {"title": f"Page {index}", "level": 0, "content": page}
                for index, page in enumerate(pages, 1)
            ],
            "tables": [],
        },
    }
    return text, parsed


def test_sections_keep_pages_and_chunk_character_ranges():
    text, parsed = _paged_paper()
    result = PaperStructureParser(chunk_size=200, overlap=20).parse(parsed, _analysis())

    by_type = {section.section_type: section for section in result.sections}
    assert by_type["abstract"].page_start == 1
    assert by_type["methods"].page_start == 1
    assert by_type["results"].page_start == 2
    assert by_type["discussion"].page_start == 2
    assert by_type["conclusion"].page_start == 3
    assert by_type["references"].page_start == 3
    assert "limitations" in result.missing_sections
    assert "results" not in result.missing_sections
    assert "discussion" not in result.missing_sections
    assert "conclusion" not in result.missing_sections

    for chunk in result.chunks:
        assert chunk["char_end"] > chunk["char_start"]
        assert text[chunk["char_start"]:chunk["char_end"]] == chunk["text"]
        assert chunk["section_ordinal"] > 0
    assert [chunk["chunk_index"] for chunk in result.chunks] == list(range(len(result.chunks)))


def test_compound_heading_counts_both_section_types():
    parsed = {
        "content": "Results and Discussion\nThe treatment changed the outcome.",
        "metadata": {"format": "pdf"},
        "extra": {"sections": [], "tables": []},
    }

    result = PaperStructureParser().parse(parsed, _analysis())

    section = result.sections[0]
    assert section.section_type == "results"
    assert section.secondary_types == ["discussion"]
    assert "results" not in result.missing_sections
    assert "discussion" not in result.missing_sections


def test_table_section_keeps_exact_text_location():
    text = "Results\nOutcome\nRecovered\n"
    parsed = {
        "content": text,
        "metadata": {"format": "pdf"},
        "extra": {
            "sections": [],
            "tables": [{"headers": ["Outcome"], "rows": [["Recovered"]]}],
        },
    }

    result = PaperStructureParser().parse(parsed, _analysis())

    table = next(section for section in result.sections if section.section_type == "table")
    assert text[table.char_start:table.char_end] == "Outcome\nRecovered"
    assert table.metadata["location_exact"] is True
    assert any(chunk["section_type"] == "table" for chunk in result.chunks)


def test_table_without_matching_text_is_marked_as_unlocated():
    parsed = {
        "content": "Results\nThe table was extracted separately.",
        "metadata": {"format": "pdf"},
        "extra": {
            "sections": [],
            "tables": [{"headers": ["Outcome"], "rows": [["Recovered"]]}],
        },
    }

    result = PaperStructureParser().parse(parsed, _analysis())

    table = next(section for section in result.sections if section.section_type == "table")
    assert table.metadata["location_exact"] is False
    assert table.char_start == table.char_end == 0
    table_chunk = next(chunk for chunk in result.chunks if chunk["section_type"] == "table")
    assert table_chunk["char_start"] == table_chunk["char_end"] == 0
    assert table_chunk["location_exact"] is False
    assert "table_location_unavailable" in result.warnings


def test_figure_captions_are_kept_with_page_and_text_location():
    text = "Results\nThe outcome is shown below.\n\nFigure 1. Study flow\n"
    parsed = {
        "content": text,
        "metadata": {"format": "pdf"},
        "extra": {
            "sections": [{"title": "Page 1", "content": text}],
            "tables": [],
        },
    }

    result = PaperStructureParser().parse(parsed, _analysis())

    figure = next(
        section for section in result.sections
        if section.section_type == "figure_caption"
    )
    assert figure.page_start == figure.page_end == 1
    assert text[figure.char_start:figure.char_end] == "Figure 1. Study flow"
    assert result.chunks[-1]["section_type"] == "figure_caption"


def test_empty_pdf_reports_that_ocr_is_needed():
    parsed = {"content": "", "metadata": {"format": "pdf"}, "extra": {}}

    result = PaperStructureParser().parse(parsed, _analysis())

    assert result.warnings == ["ocr_required"]
    assert "abstract" in result.missing_sections
