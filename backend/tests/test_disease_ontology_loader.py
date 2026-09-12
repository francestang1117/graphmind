"""Integrity checks for the versioned local disease terminology package."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from app.services.medical.terminology.loader import DiseaseOntology, DiseaseOntologyError


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "app/services/medical/terminology/resources"

EXPECTED_MESH_NAMES = {
    "mesh:D000544": "Alzheimer Disease",
    "mesh:D000690": "Amyotrophic Lateral Sclerosis",
    "mesh:D000795": "Fabry disease",
    "mesh:D001943": "Breast Neoplasms",
    "mesh:D003920": "Diabetes Mellitus",
    "mesh:D004675": "Encephalitis",
    "mesh:D005776": "Gaucher disease",
    "mesh:D005901": "Glaucoma",
    "mesh:D006073": "Gout",
    "mesh:D006816": "Huntington Disease",
    "mesh:D006973": "Hypertension",
    "mesh:D008113": "Liver cancer",
    "mesh:D008175": "Lung Neoplasms",
    "mesh:D008457": "Measles",
    "mesh:D008545": "Melanoma",
    "mesh:D009136": "Muscular Dystrophies",
    "mesh:D010300": "Parkinson Disease",
    "mesh:D012507": "Sarcoidosis",
    "mesh:D013274": "Stomach cancer",
    "mesh:D020388": "Duchenne Muscular Dystrophy",
    "mesh:D035583": "Rare Diseases",
}


def test_default_ontology_has_versioned_integrity_metadata() -> None:
    ontology = DiseaseOntology.from_directory(RESOURCE_DIR)

    assert ontology.version
    assert ontology.manifest.record_count == len(ontology.concepts)
    assert ontology.manifest.alias_count == sum(len(item.aliases) for item in ontology.concepts)
    assert ontology.data_sha256 == ontology.manifest.sha256
    assert ontology.manifest.source_revision == (
        "114e6da9d4ab3dfdc86af8a084def14fef7d3432"
    )
    assert all("blob/main" not in source.source_url for source in ontology.manifest.sources)
    assert ontology.get("mesh:D006816").preferred_name_zh == "亨廷顿病"


def test_default_seed_has_reviewed_mesh_id_name_pairs() -> None:
    ontology = DiseaseOntology.from_directory(RESOURCE_DIR)

    assert {
        concept.concept_id: concept.preferred_name_en
        for concept in ontology.concepts
    } == EXPECTED_MESH_NAMES
    assert ontology.get("mesh:D000795").mesh_id == "D000795"
    assert ontology.get("mesh:D005776").mesh_id == "D005776"


def test_checksum_mismatch_rejects_the_package(tmp_path) -> None:
    resource_copy = tmp_path / "resources"
    resource_copy.mkdir()
    for name in ("manifest.json", "disease_concepts.jsonl.gz"):
        (resource_copy / name).write_bytes((RESOURCE_DIR / name).read_bytes())

    manifest = json.loads((resource_copy / "manifest.json").read_text(encoding="utf-8"))
    manifest["sha256"] = "0" * 64
    (resource_copy / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(DiseaseOntologyError, match="checksum"):
        DiseaseOntology.from_directory(resource_copy)


def test_corrupt_jsonl_record_rejects_the_package(tmp_path) -> None:
    resource_copy = tmp_path / "resources"
    resource_copy.mkdir()
    manifest = json.loads((RESOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    raw = gzip.decompress((RESOURCE_DIR / manifest["data_file"]).read_bytes())
    corrupt = gzip.compress(raw + b"{not-json}\n", mtime=0)
    (resource_copy / manifest["data_file"]).write_bytes(corrupt)
    manifest["sha256"] = hashlib.sha256(corrupt).hexdigest()
    manifest["record_count"] = 22
    (resource_copy / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(DiseaseOntologyError, match="record 22"):
        DiseaseOntology.from_directory(resource_copy)
