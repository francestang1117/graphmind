"""Integrity checks for the versioned local disease terminology package."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from app.services.medical.terminology.loader import DiseaseOntology, DiseaseOntologyError


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "app/services/medical/terminology/resources"


def test_default_ontology_has_versioned_integrity_metadata() -> None:
    ontology = DiseaseOntology.from_directory(RESOURCE_DIR)

    assert ontology.version
    assert ontology.manifest.record_count == len(ontology.concepts)
    assert ontology.manifest.alias_count == sum(len(item.aliases) for item in ontology.concepts)
    assert ontology.data_sha256 == ontology.manifest.sha256
    assert ontology.get("mesh:D006816").preferred_name_zh == "亨廷顿病"


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
