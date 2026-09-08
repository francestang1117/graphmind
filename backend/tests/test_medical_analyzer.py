"""Tests for the medical step inside the existing parse flow."""

from app.services.medical.analyzer import analyze_document


class _Repository:
    def __init__(self):
        self.calls = []

    def replace_analysis(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return True


def _paper() -> dict:
    text = """Abstract
Patients with disease received the intervention.

Methods
We enrolled participants in a clinical study.

Results
The treatment improved the primary outcome.

Discussion
The authors interpret the observed result.

Conclusion
Further research is needed.

References
10.1000/example"""
    return {
        "content": text,
        "chunks": [{"text": text, "type": "page", "page": 1}],
        "metadata": {"format": "pdf"},
        "extra": {
            "sections": [{"title": "Page 1", "content": text}],
            "tables": [],
        },
    }


def test_paper_analysis_replaces_generic_chunks_and_is_persisted():
    parsed = _paper()
    repository = _Repository()

    result = analyze_document(
        parsed,
        filename="paper.pdf",
        original_filename="paper.pdf",
        document_id="document-a",
        user_id="user-a",
        workspace_id="workspace-a",
        repository=repository,
    )

    assert result["document_kind"] == "research_paper"
    assert {section["section_type"] for section in result["sections"]} >= {
        "abstract",
        "methods",
        "results",
        "discussion",
        "conclusion",
    }
    assert parsed["chunks"]
    assert all(chunk["type"] == "medical_section" for chunk in parsed["chunks"])
    assert all(chunk["page_start"] == 1 for chunk in parsed["chunks"])
    assert repository.calls[0][0][0] == "document-a"
    assert repository.calls[0][1]["user_id"] == "user-a"
    assert repository.calls[0][1]["workspace_id"] == "workspace-a"


def test_guideline_analysis_uses_guideline_sections_and_roles():
    text = """Clinical Practice Guideline

Scope
This guideline covers adults with the condition.

Recommendations
Clinicians should discuss treatment options.

Population
The target population is adults.

Evidence
The recommendation is based on moderate certainty evidence.

Contraindications
The intervention is not for this population."""
    parsed = {
        "title": "Clinical Practice Guideline",
        "content": text,
        "chunks": [{"text": text, "type": "page", "page": 1}],
        "metadata": {"format": "pdf"},
        "extra": {
            "sections": [{"title": "Page 1", "content": text}],
            "tables": [],
        },
    }

    result = analyze_document(
        parsed,
        filename="guideline.pdf",
        original_filename="guideline.pdf",
        document_id="guideline-a",
        user_id="user-a",
        workspace_id="workspace-a",
        repository=_Repository(),
    )

    by_type = {section["section_type"]: section for section in result["sections"]}
    assert result["document_kind"] == "guideline"
    assert {
        "scope",
        "recommendations",
        "population",
        "evidence",
        "contraindications",
    } <= by_type.keys()
    assert by_type["recommendations"]["metadata"]["evidence_role"] == (
        "guideline_recommendation"
    )
    assert by_type["evidence"]["metadata"]["evidence_role"] == "guideline_evidence"
    assert all(chunk["type"] == "medical_section" for chunk in parsed["chunks"])
    assert any(
        chunk["section_type"] == "recommendations"
        and chunk["evidence_role"] == "guideline_recommendation"
        for chunk in parsed["chunks"]
    )


def test_ordinary_document_keeps_the_generic_parse_path():
    parsed = {
        "content": "FastAPI and Python",
        "chunks": [{"text": "FastAPI and Python", "type": "paragraph"}],
        "metadata": {"format": "txt"},
        "extra": {"sections": [], "tables": []},
    }
    repository = _Repository()

    result = analyze_document(
        parsed,
        filename="notes.txt",
        document_id="document-b",
        user_id="user-a",
        workspace_id="workspace-a",
        repository=repository,
    )

    assert result["document_kind"] == "unknown"
    assert parsed["chunks"][0]["type"] == "paragraph"
    assert repository.calls
