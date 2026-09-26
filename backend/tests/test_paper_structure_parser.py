"""Tests for paper sections, page ranges, and traceable chunks."""

from app.services.medical.models import MedicalDocumentAnalysis
from app.services.medical.paper_structure_parser import PaperStructureParser
from app.services.medical.ai.context_builder import ContextBuilder


def _analysis(
    language: str = "en",
    document_kind: str = "research_paper",
) -> MedicalDocumentAnalysis:
    return MedicalDocumentAnalysis(
        document_kind=document_kind,
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


def test_guideline_sections_keep_recommendation_and_evidence_roles():
    text = (
        "Clinical guideline\n\n"
        "Scope\nThis guideline covers adults with the condition.\n\n"
        "Recommendations\nClinicians should discuss treatment options.\n\n"
        "Population\nThe target population is adults.\n\n"
        "Evidence\nThe recommendation is based on moderate certainty evidence.\n\n"
        "Contraindications\nThe intervention is not for this population."
    )
    parsed = {
        "content": text,
        "metadata": {"format": "pdf"},
        "extra": {"sections": [], "tables": []},
    }

    result = PaperStructureParser(chunk_size=200, overlap=20).parse(
        parsed,
        _analysis(document_kind="guideline"),
    )

    by_type = {section.section_type: section for section in result.sections}
    assert {"scope", "recommendations", "population", "evidence", "contraindications"} <= by_type.keys()
    assert result.missing_sections == []
    assert by_type["recommendations"].metadata["evidence_role"] == "guideline_recommendation"
    assert by_type["evidence"].metadata["evidence_role"] == "guideline_evidence"
    assert by_type["contraindications"].metadata["evidence_role"] == "guideline_contraindication"
    recommendation_chunk = next(
        chunk for chunk in result.chunks if chunk["section_type"] == "recommendations"
    )
    assert recommendation_chunk["page_start"] is None
    assert recommendation_chunk["evidence_role"] == "guideline_recommendation"


def test_layout_word_hints_do_not_split_a_compound_heading():
    text = "Results and Discussion\nThe study result needs interpretation."
    parsed = {
        "content": text,
        "metadata": {
            "format": "pdf",
            # pdfplumber can return one large-font word per hint even when
            # the extracted text contains the complete heading.
            "headings": [
                {"text": "Results", "page": 1},
                {"text": "Discussion", "page": 1},
            ],
        },
        "extra": {
            "sections": [{"title": "Page 1", "level": 0, "content": text}],
            "tables": [],
        },
    }

    result = PaperStructureParser().parse(parsed, _analysis())

    sections = [section for section in result.sections if section.original_title]
    assert [section.section_type for section in sections] == ["results"]
    assert sections[0].original_title == "Results and Discussion"
    assert sections[0].secondary_types == ["discussion"]


def test_docx_without_heading_styles_still_finds_body_headings():
    text = (
        "Paper title\n\n"
        "Abstract\nPatients were included.\n\n"
        "Methods\nThe study enrolled participants.\n\n"
        "Results\nThe treatment changed the outcome."
    )
    parsed = {
        "content": text,
        "metadata": {"format": "docx"},
        "extra": {
            # This is the generic parser's fallback block when the DOCX uses
            # bold text or line breaks instead of Word Heading styles.
            "sections": [{"title": "Introduction", "level": 0, "content": text}],
            "tables": [],
        },
    }

    result = PaperStructureParser().parse(parsed, _analysis())
    section_types = {section.section_type for section in result.sections}

    assert {"title", "abstract", "methods", "results"} <= section_types
    assert "introduction" not in section_types
    assert "abstract" not in result.missing_sections
    assert "methods" not in result.missing_sections
    assert "results" not in result.missing_sections


def test_chunk_page_range_is_narrower_than_a_multi_page_section():
    page_one = "Results\n" + ("The intervention improved the primary outcome. " * 8)
    page_two = ("Follow-up results remained stable. " * 8) + "\n\nDiscussion\nThe authors interpret the findings."
    text = "\n\n".join((page_one, page_two))
    parsed = {
        "content": text,
        "metadata": {"format": "pdf"},
        "extra": {
            "sections": [
                {"title": "Page 1", "level": 0, "content": page_one},
                {"title": "Page 2", "level": 0, "content": page_two},
            ],
            "tables": [],
        },
    }

    result = PaperStructureParser(chunk_size=200, overlap=20).parse(parsed, _analysis())
    results_section = next(
        section for section in result.sections if section.section_type == "results"
    )
    result_chunks = [
        chunk for chunk in result.chunks if chunk["section_type"] == "results"
    ]

    assert results_section.page_start == 1
    assert results_section.page_end == 2
    assert any(
        chunk["page_start"] == chunk["page_end"] == 2
        for chunk in result_chunks
    )
    assert all(chunk["section_page_start"] == 1 for chunk in result_chunks)
    assert all(chunk["section_page_end"] == 2 for chunk in result_chunks)


def test_chunks_start_and_end_on_sentence_boundaries():
    text = "Results\n" + (
        "Fabry patients had higher Gb3 levels than controls. "
        "The difference was most pronounced in classic disease. "
        "Follow-up measurements remained stable. "
        "Urinary isoforms were also higher in the classic subgroup. "
        "The observed pattern was consistent across the measured samples."
    )
    parsed = {
        "content": text,
        "metadata": {"format": "pdf"},
        "extra": {"sections": [], "tables": []},
    }

    result = PaperStructureParser(chunk_size=200, overlap=40).parse(parsed, _analysis())
    chunks = [chunk for chunk in result.chunks if chunk["section_type"] == "results"]

    assert len(chunks) >= 2
    assert all(chunk["starts_at_sentence_boundary"] for chunk in chunks)
    assert all(chunk["ends_at_sentence_boundary"] for chunk in chunks)
    assert all(text[chunk["char_start"]:chunk["char_end"]] == chunk["text"] for chunk in chunks)
    assert all(not chunk["text"].lstrip().startswith(("ary ", "orm,")) for chunk in chunks)


def test_structured_abstract_labels_get_distinct_semantic_sections():
    text = (
        "Abstract\n"
        "Objectives The study assessed biomarker levels. "
        "Methods Plasma samples from 15 patients and 36 controls were analyzed. "
        "Results Patients had higher levels than controls. "
        "Conclusion The marker may support further study."
    )
    parsed = {
        "content": text,
        "metadata": {"format": "pdf"},
        "extra": {"sections": [], "tables": []},
    }

    result = PaperStructureParser().parse(parsed, _analysis())

    assert {section.section_type for section in result.sections} >= {
        "abstract",
        "scope",
        "methods",
        "results",
        "conclusion",
    }
    assert any(
        chunk["section_type"] == "results"
        and "Patients had higher levels" in chunk["text"]
        for chunk in result.chunks
    )
    assert not any(
        chunk["section_type"] == "results" and "Objectives" in chunk["text"]
        for chunk in result.chunks
    )


def test_non_medical_tail_stops_conclusion_before_acknowledgements_and_funding():
    text = (
        "Conclusion\nThe reported association should be interpreted cautiously.\n\n"
        "Acknowledgements\nWe thank the participating clinics.\n\n"
        "Funding\nSupported by a research grant.\n\n"
        "References\n1. Smith J. Fabry disease. 2020;12:34."
    )
    parsed = {"content": text, "metadata": {"format": "pdf"}, "extra": {"sections": [], "tables": []}}

    result = PaperStructureParser().parse(parsed, _analysis())

    conclusion = next(section for section in result.sections if section.section_type == "conclusion")
    assert "Acknowledgements" not in conclusion.text
    assert "Funding" not in conclusion.text
    assert {section.section_type for section in result.sections} >= {
        "conclusion",
        "acknowledgements",
        "funding",
        "references",
    }
    context = ContextBuilder().build(result.chunks)
    assert not any(
        item.section_type in {"acknowledgements", "funding", "references"}
        for item in context.evidence
    )


def test_content_based_reference_tail_requires_more_than_one_bibliographic_line():
    text = (
        "Conclusion\nThe finding is consistent with one prior report (Smith, 2020).\n\n"
        "1. Smith J. Fabry disease. 2020;12:34.\n"
        "2. Jones A. Biomarkers in Fabry disease. 2021;13:45."
    )
    parsed = {"content": text, "metadata": {"format": "pdf"}, "extra": {"sections": [], "tables": []}}

    result = PaperStructureParser().parse(parsed, _analysis())
    conclusion = next(section for section in result.sections if section.section_type == "conclusion")

    assert "consistent with one prior report" in conclusion.text
    assert "Smith J. Fabry disease" not in conclusion.text


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


def test_pdf_block_metadata_rejects_caption_and_reference_mixed_chunks():
    text = (
        "Results\n"
        "Clean result sentence.\n"
        "Figure 1. Study flow and participant exclusions.\n"
        "Intern Med 63: 1531-1538, 2024\n"
    )
    caption_start = text.index("Figure 1")
    citation_start = text.index("Intern Med")
    parsed = {
        "content": text,
        "metadata": {
            "format": "pdf",
            "pdf_blocks": [
                {
                    "page": 1,
                    "kind": "body",
                    "block_type": "body",
                    "column": "left",
                    "char_start": text.index("Clean"),
                    "char_end": caption_start,
                    "medical_evidence": True,
                    "quality_flags": [],
                },
                {
                    "page": 1,
                    "kind": "figure_caption",
                    "block_type": "figure_caption",
                    "column": "left",
                    "char_start": caption_start,
                    "char_end": citation_start,
                    "medical_evidence": False,
                    "quality_flags": ["caption_body_mixed"],
                },
                {
                    "page": 1,
                    "kind": "metadata",
                    "block_type": "metadata",
                    "column": "left",
                    "char_start": citation_start,
                    "char_end": len(text),
                    "medical_evidence": False,
                    "quality_flags": ["reference_like"],
                },
            ],
        },
        "extra": {
            "sections": [{"title": "Page 1", "content": text}],
            "tables": [],
        },
    }

    result = PaperStructureParser().parse(parsed, _analysis())
    result_chunks = [chunk for chunk in result.chunks if chunk["section_type"] == "results"]

    assert [chunk["text"] for chunk in result_chunks] == ["Clean result sentence."]
    assert result_chunks[0]["pdf_block_type"] == "body"
    assert result_chunks[0]["medical_evidence"] is True


def test_empty_pdf_reports_that_ocr_is_needed():
    parsed = {"content": "", "metadata": {"format": "pdf"}, "extra": {}}

    result = PaperStructureParser().parse(parsed, _analysis())

    assert result.warnings == ["ocr_required"]
    assert "abstract" in result.missing_sections
