"""Deterministic, offline ontology build checks."""

import json
from pathlib import Path

import pytest

from scripts.build_disease_ontology import build_ontology
from app.services.medical.terminology.loader import DiseaseOntology


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "app/services/medical/terminology/resources"
SEED_FILE = Path(__file__).resolve().parents[1] / "data/curated_disease_concepts.jsonl"
ALIASES_FILE = Path(__file__).resolve().parents[1] / "data/curated_zh_disease_aliases.yaml"


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


def test_checked_in_seed_rebuild_matches_shipped_package(tmp_path) -> None:
    rebuilt_dir = tmp_path / "rebuilt"
    manifest = build_ontology(
        output=rebuilt_dir,
        curated_seed_file=SEED_FILE,
        zh_aliases=ALIASES_FILE,
        ontology_version="curated-seed-2026.09.2",
        mesh_release="seed",
        generated_at="2026-09-12T00:00:00Z",
    )

    shipped_manifest = json.loads(
        (RESOURCE_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == shipped_manifest
    assert (rebuilt_dir / "disease_concepts.jsonl.gz").read_bytes() == (
        RESOURCE_DIR / "disease_concepts.jsonl.gz"
    ).read_bytes()


def test_mesh_xml_keeps_disease_tree_and_excludes_non_disease_records(tmp_path) -> None:
    mesh_file = tmp_path / "desc.xml"
    mesh_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DescriptorRecordSet xmlns="http://www.nlm.nih.gov/mesh/">
  <DescriptorRecord>
    <DescriptorUI>D000795</DescriptorUI>
    <DescriptorName><String>Fabry Disease</String></DescriptorName>
    <TreeNumberList><TreeNumber>C18.452.648</TreeNumber></TreeNumberList>
    <ConceptList><Concept><TermList><Term><String>Anderson-Fabry Disease</String></Term></TermList></Concept></ConceptList>
  </DescriptorRecord>
  <DescriptorRecord>
    <DescriptorUI>D000001</DescriptorUI>
    <DescriptorName><String>Calcimycin</String></DescriptorName>
    <TreeNumberList><TreeNumber>D03.633</TreeNumber></TreeNumberList>
  </DescriptorRecord>
</DescriptorRecordSet>
""",
        encoding="utf-8",
    )

    manifest = build_ontology(
        output=tmp_path / "output",
        mesh_file=mesh_file,
        ontology_version="mesh-test-1",
        mesh_release="2026",
        generated_at="2026-09-12T00:00:00Z",
    )

    ontology = DiseaseOntology.from_directory(tmp_path / "output")
    assert ontology.get("mesh:D000795") is not None
    assert ontology.get("mesh:D000001") is None
    assert manifest["record_count"] == 1
    source = manifest["sources"][0]
    assert source["file_name"] == "desc.xml"
    assert len(source["file_sha256"]) == 64


def test_empty_or_non_disease_explicit_mesh_source_fails(tmp_path) -> None:
    mesh_file = tmp_path / "non-disease.xml"
    mesh_file.write_text(
        """<DescriptorRecordSet>
  <DescriptorRecord>
    <DescriptorUI>D000001</DescriptorUI>
    <DescriptorName><String>Calcimycin</String></DescriptorName>
    <TreeNumberList><TreeNumber>D03.633</TreeNumber></TreeNumberList>
  </DescriptorRecord>
</DescriptorRecordSet>
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="MeSH source produced no usable records"):
        build_ontology(output=tmp_path / "output", mesh_file=mesh_file)


def test_orphanet_xml_reads_the_standard_orpha_code_element(tmp_path) -> None:
    orphanet_file = tmp_path / "en_product1.xml"
    orphanet_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<ORPHADATA xmlns="http://www.orphadata.com">
  <DisorderList>
    <Disorder id="6">
      <OrphaCode>585</OrphaCode>
      <Name>Fabry disease</Name>
      <SynonymList><Synonym>Anderson-Fabry disease</Synonym></SynonymList>
    </Disorder>
  </DisorderList>
</ORPHADATA>
""",
        encoding="utf-8",
    )

    manifest = build_ontology(
        output=tmp_path / "output",
        orphanet_file=orphanet_file,
        ontology_version="orpha-test-1",
        orphanet_release="2026-01",
        generated_at="2026-09-12T00:00:00Z",
    )

    ontology = DiseaseOntology.from_directory(tmp_path / "output")
    concept = ontology.get("orpha:585")
    assert concept is not None
    assert concept.orpha_code == "585"
    assert any(alias.text == "Anderson-Fabry disease" for alias in concept.aliases)
    assert manifest["sources"][0]["release"] == "2026-01"


def test_curated_preferred_name_cannot_override_seed_name(tmp_path) -> None:
    seed = tmp_path / "seed.jsonl"
    seed.write_text(
        json.dumps(
            {
                "concept_id": "mesh:D000795",
                "preferred_name_en": "Fabry disease",
                "mesh_id": "D000795",
                "aliases": ["Fabry disease"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.yaml"
    aliases.write_text(
        "concepts:\n"
        "  - concept_id: mesh:D000795\n"
        "    preferred_name_en: Not Fabry disease\n"
        "    aliases: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="curated preferred name conflicts"):
        build_ontology(
            output=tmp_path / "output",
            mesh_file=seed,
            zh_aliases=aliases,
        )
