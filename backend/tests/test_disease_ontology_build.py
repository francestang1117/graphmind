"""Deterministic, offline ontology build checks."""

import json

from scripts.build_disease_ontology import build_ontology
from app.services.medical.terminology.loader import DiseaseOntology


def test_build_is_deterministic_and_marks_short_aliases(tmp_path) -> None:
    source = tmp_path / "mesh.jsonl"
    source.write_text(
        json.dumps(
            {
                "concept_id": "mesh:D123456",
                "preferred_name_en": "Example Disease",
                "mesh_id": "D123456",
                "aliases": ["example disease", "EXD"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.yaml"
    aliases.write_text(
        "concepts:\n"
        "  - concept_id: mesh:D123456\n"
        "    preferred_name_zh: 示例病\n"
        "    aliases:\n"
        "      - text: 示例病\n"
        "        language: zh-Hans\n",
        encoding="utf-8",
    )

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = build_ontology(
        output=first_dir,
        mesh_file=source,
        zh_aliases=aliases,
        ontology_version="test-ontology-1",
        generated_at="2026-09-12T00:00:00Z",
    )
    second = build_ontology(
        output=second_dir,
        mesh_file=source,
        zh_aliases=aliases,
        ontology_version="test-ontology-1",
        generated_at="2026-09-12T00:00:00Z",
    )

    assert first == second
    assert (first_dir / "disease_concepts.jsonl.gz").read_bytes() == (
        second_dir / "disease_concepts.jsonl.gz"
    ).read_bytes()
    ontology = DiseaseOntology.from_directory(first_dir)
    concept = ontology.get("mesh:D123456")
    assert concept is not None
    assert concept.preferred_name_zh == "示例病"
    assert next(alias for alias in concept.aliases if alias.text == "EXD").resolution == (
        "confirmation_required"
    )
