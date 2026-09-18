"""Bounded-read regressions for disease profile pagination."""

from __future__ import annotations

import uuid

from app.core.database import SessionLocal
from app.models.persistence import DocumentDiseaseLinkRecord, DocumentRecord
from app.services.medical.disease_profile.aggregator import DiseaseProfileAggregator
from app.services.medical.disease_profile.repository import (
    DiseaseProfileRepository,
    ProfileInputOptions,
)
from app.services.medical.disease_profile.service import DiseaseProfileService


def _document(document_id: str, user_id: str, workspace_id: str) -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        user_id=user_id,
        workspace_id=workspace_id,
        filename=f"{document_id}.pdf",
        stored_filename=f"stored-{document_id}.pdf",
        original_filename=f"{document_id}.pdf",
        file_extension="pdf",
        file_type="pdf",
        mime_type="application/pdf",
        file_hash=f"hash-{document_id}",
        file_path=f"/tmp/{document_id}.pdf",
        file_size=10,
        status="completed",
        document_kind="research_paper",
        language="en",
        parsed_source_hash=f"parsed-{document_id}",
    )


def _input_record(concept_id: str, document_id: str) -> dict:
    return {
        "link": {
            "concept_id": concept_id,
            "preferred_name_en": "Test Disease",
            "preferred_name_zh": "测试疾病",
            "ontology_version": "test-v1",
            "updated_at": "2026-09-18T00:00:00+00:00",
        },
        "document": {
            "document_id": document_id,
            "title": f"{document_id}.pdf",
            "document_kind": "research_paper",
            "language": "en",
            "document_date": "2026-01-01",
            "file_hash": f"hash-{document_id}",
            "parsed_source_hash": f"parsed-{document_id}",
            "modified_at": "2026-09-18T00:00:00+00:00",
        },
        "analyses": [],
        "matches": [],
        "questions": [],
    }


def test_repository_pages_concepts_before_loading_profile_inputs():
    suffix = uuid.uuid4().hex
    user_id = f"perf-user-{suffix}"
    workspace_id = f"perf-workspace-{suffix}"
    other_workspace_id = f"other-workspace-{suffix}"
    other_user_id = f"other-user-{suffix}"
    rows: list[tuple[str, str]] = []

    try:
        with SessionLocal() as db:
            for index in range(3):
                document_id = f"perf-document-{suffix}-{index}"
                concept_id = f"mesh:PERF-{index:03d}"
                rows.append((document_id, concept_id))
                db.add(_document(document_id, user_id, workspace_id))
            db.flush()
            for index, (document_id, concept_id) in enumerate(rows):
                db.add(
                    DocumentDiseaseLinkRecord(
                        id=f"perf-link-{suffix}-{index}",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document_id,
                        concept_id=concept_id,
                        preferred_name_en="Test Disease",
                        preferred_name_zh="测试疾病",
                        matched_alias="Test Disease",
                        ontology_version="test-v1",
                        link_source="manual_selection",
                    )
                )
            db.add(
                _document(
                    f"perf-document-{suffix}-other-workspace",
                    user_id,
                    other_workspace_id,
                )
            )
            db.add(
                _document(
                    f"perf-document-{suffix}-other-user",
                    other_user_id,
                    workspace_id,
                )
            )
            db.flush()
            db.add(
                DocumentDiseaseLinkRecord(
                    id=f"perf-link-{suffix}-other-workspace",
                    user_id=user_id,
                    workspace_id=other_workspace_id,
                    document_id=f"perf-document-{suffix}-other-workspace",
                    concept_id="mesh:PERF-900",
                    preferred_name_en="Other Workspace Disease",
                    preferred_name_zh="其他项目疾病",
                    matched_alias="Other Workspace Disease",
                    ontology_version="test-v1",
                    link_source="manual_selection",
                )
            )
            db.add(
                DocumentDiseaseLinkRecord(
                    id=f"perf-link-{suffix}-other-user",
                    user_id=other_user_id,
                    workspace_id=workspace_id,
                    document_id=f"perf-document-{suffix}-other-user",
                    concept_id="mesh:PERF-901",
                    preferred_name_en="Other User Disease",
                    preferred_name_zh="其他用户疾病",
                    matched_alias="Other User Disease",
                    ontology_version="test-v1",
                    link_source="manual_selection",
                )
            )
            db.commit()

        repository = DiseaseProfileRepository()
        first_page = repository.list_profile_concept_page(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=2,
        )
        assert [item["concept_id"] for item in first_page["items"]] == [
            "mesh:PERF-000",
            "mesh:PERF-001",
        ]
        assert first_page["next_cursor"] == "mesh:PERF-001"

        second_page = repository.list_profile_concept_page(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=2,
            after_concept_id=first_page["next_cursor"],
        )
        assert [item["concept_id"] for item in second_page["items"]] == ["mesh:PERF-002"]
        assert second_page["next_cursor"] is None

        selected = repository.load_profile_inputs(
            user_id=user_id,
            workspace_id=workspace_id,
            concept_ids=["mesh:PERF-001"],
            include=ProfileInputOptions(
                analyses=False,
                evidence=False,
                literature_matches=False,
                clinician_questions=False,
            ),
        )
        assert list(selected) == ["mesh:PERF-001"]
        assert [item["document"]["document_id"] for item in selected["mesh:PERF-001"]] == [
            rows[1][0]
        ]
    finally:
        with SessionLocal() as db:
            db.query(DocumentDiseaseLinkRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentDiseaseLinkRecord).filter_by(
                user_id=user_id,
                workspace_id=other_workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentDiseaseLinkRecord).filter_by(
                user_id=other_user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentRecord).filter_by(
                user_id=user_id,
                workspace_id=other_workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentRecord).filter_by(
                user_id=other_user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.commit()


def test_repository_groups_same_concept_across_ontology_versions():
    suffix = uuid.uuid4().hex
    user_id = f"version-user-{suffix}"
    workspace_id = f"version-workspace-{suffix}"
    document_ids = [f"version-document-{suffix}-{index}" for index in range(2)]

    try:
        with SessionLocal() as db:
            for index, document_id in enumerate(document_ids):
                db.add(_document(document_id, user_id, workspace_id))
                db.flush()
                db.add(
                    DocumentDiseaseLinkRecord(
                        id=f"version-link-{suffix}-{index}",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document_id,
                        concept_id="mesh:D000795",
                        preferred_name_en=(
                            "Fabry Disease" if index == 0 else "Fabry disease"
                        ),
                        preferred_name_zh="法布雷病",
                        matched_alias="法布雷病",
                        ontology_version=f"test-v{index + 1}",
                        link_source="manual_selection",
                    )
                )
            db.commit()

        repository = DiseaseProfileRepository()
        page = repository.list_profile_concept_page(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=1,
        )

        assert [item["concept_id"] for item in page["items"]] == ["mesh:D000795"]
        assert page["items"][0]["document_count"] == 2
        assert page["next_cursor"] is None

        profile = DiseaseProfileService().list_profiles(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=1,
        )
        assert [item["concept_id"] for item in profile["items"]] == ["mesh:D000795"]
        assert profile["items"][0]["document_count"] == 2
        assert profile["next_cursor"] is None
    finally:
        with SessionLocal() as db:
            db.query(DocumentDiseaseLinkRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.commit()


def test_repository_concept_page_has_stable_fifty_item_boundary():
    suffix = uuid.uuid4().hex
    user_id = f"boundary-user-{suffix}"
    workspace_id = f"boundary-workspace-{suffix}"
    document_ids = [f"boundary-document-{suffix}-{index}" for index in range(51)]

    try:
        with SessionLocal() as db:
            for index, document_id in enumerate(document_ids):
                db.add(_document(document_id, user_id, workspace_id))
            db.flush()
            for index, document_id in enumerate(document_ids):
                db.add(
                    DocumentDiseaseLinkRecord(
                        id=f"boundary-link-{suffix}-{index}",
                        user_id=user_id,
                        workspace_id=workspace_id,
                        document_id=document_id,
                        concept_id=f"mesh:BOUNDARY-{index:03d}",
                        preferred_name_en="Boundary Disease",
                        preferred_name_zh="边界疾病",
                        matched_alias="Boundary Disease",
                        ontology_version="test-v1",
                        link_source="manual_selection",
                    )
                )
            db.commit()

        repository = DiseaseProfileRepository()
        first_page = repository.list_profile_concept_page(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=50,
        )
        second_page = repository.list_profile_concept_page(
            user_id=user_id,
            workspace_id=workspace_id,
            limit=50,
            after_concept_id=first_page["next_cursor"],
        )

        assert len(first_page["items"]) == 50
        assert first_page["next_cursor"] == "mesh:BOUNDARY-049"
        assert [item["concept_id"] for item in second_page["items"]] == [
            "mesh:BOUNDARY-050"
        ]
        assert second_page["next_cursor"] is None
    finally:
        with SessionLocal() as db:
            db.query(DocumentDiseaseLinkRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.query(DocumentRecord).filter_by(
                user_id=user_id,
                workspace_id=workspace_id,
            ).delete(synchronize_session=False)
            db.commit()


def test_service_loads_only_the_current_concept_page():
    captured: dict[str, object] = {}

    class Repository:
        def list_profile_concept_page(self, **kwargs):
            captured["page"] = kwargs
            return {
                "items": [
                    {"concept_id": "mesh:A"},
                    {"concept_id": "mesh:B"},
                ],
                "next_cursor": "mesh:B",
            }

        def load_profile_inputs(self, **kwargs):
            captured["inputs"] = kwargs
            return {
                "mesh:A": [_input_record("mesh:A", "doc-a")],
                "mesh:B": [_input_record("mesh:B", "doc-b")],
            }

    service = DiseaseProfileService(repository=Repository())
    result = service.list_profiles(
        user_id="user-1",
        workspace_id="workspace-1",
        limit=2,
        cursor_concept_id="mesh:before",
    )

    assert [item["concept_id"] for item in result["items"]] == ["mesh:A", "mesh:B"]
    assert result["next_cursor"] == "mesh:B"
    assert captured["page"] == {
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "limit": 2,
        "after_concept_id": "mesh:before",
    }
    assert captured["inputs"]["concept_ids"] == ["mesh:A", "mesh:B"]


def test_section_read_uses_only_its_declared_input_tables():
    captured: dict[str, object] = {}

    class Repository:
        def load_profile_inputs(self, **kwargs):
            captured.update(kwargs)
            return {"mesh:A": [_input_record("mesh:A", "doc-a")]}

    service = DiseaseProfileService(
        repository=Repository(),
        aggregator=DiseaseProfileAggregator(),
    )
    result = service.get_items(
        user_id="user-1",
        workspace_id="workspace-1",
        concept_id="mesh:A",
        section="external_studies",
        limit=20,
        offset=0,
    )

    assert result == {
        "section": "external_studies",
        "items": [],
        "total": 0,
    }
    options = captured["include"]
    assert options.analyses is True
    assert options.evidence is False
    assert options.literature_matches is True
    assert options.clinician_questions is False
