"""Build a deterministic local disease ontology package.

The script intentionally reads only files supplied by the operator. It never
downloads terminology data at runtime or during a build.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.medical.terminology.loader import DiseaseOntology
from app.services.medical.terminology.models import DiseaseAlias, DiseaseConcept
from app.services.medical.terminology.normalizer import normalize_terminology_text
from app.services.medical.terminology.pubmed_mapper import pubmed_terms_for_concept


DEFAULT_GENERATED_AT = "1970-01-01T00:00:00Z"
DEFAULT_DATA_FILE = "disease_concepts.jsonl.gz"
DEFAULT_LICENSE_URL = "https://github.com/francestang1117/graphmind"
_SHORT_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,7}$")


@dataclass
class _ConceptDraft:
    concept_id: str
    preferred_name_en: str = ""
    preferred_name_zh: str = ""
    mesh_id: str | None = None
    orpha_code: str | None = None
    pubmed_terms: list[str] | None = None
    aliases: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.aliases is None:
            self.aliases = []


def build_ontology(
    *,
    output: str | Path,
    mesh_file: str | Path | None = None,
    orphanet_file: str | Path | None = None,
    zh_aliases: str | Path | None = None,
    ontology_version: str = "local-build-1",
    mesh_release: str = "",
    orphanet_release: str = "",
    generated_at: str = DEFAULT_GENERATED_AT,
) -> dict[str, Any]:
    """Build, validate, and return a summary for one ontology package."""
    drafts: dict[str, _ConceptDraft] = {}
    source_paths: list[Path] = []

    if mesh_file:
        path = Path(mesh_file).expanduser().resolve()
        source_paths.append(path)
        _load_source_file(path, drafts, source_kind="mesh")
    if orphanet_file:
        path = Path(orphanet_file).expanduser().resolve()
        source_paths.append(path)
        _load_source_file(path, drafts, source_kind="orphanet")
    if zh_aliases:
        path = Path(zh_aliases).expanduser().resolve()
        source_paths.append(path)
        _load_curated_aliases(path, drafts)

    if not drafts:
        raise ValueError("at least one local ontology source file is required")

    concepts = _finalize_concepts(drafts)
    data = b"".join(
        (json.dumps(item.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for item in concepts
    )
    compressed = _gzip_deterministically(data)
    digest = hashlib.sha256(compressed).hexdigest()
    output_dir = Path(output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / DEFAULT_DATA_FILE).write_bytes(compressed)

    manifest = {
        "schema_version": 1,
        "ontology_version": ontology_version,
        "mesh_release": mesh_release,
        "orphanet_release": orphanet_release,
        "generated_at": generated_at,
        "data_file": DEFAULT_DATA_FILE,
        "record_count": len(concepts),
        "alias_count": sum(len(item.aliases) for item in concepts),
        "sha256": digest,
        "sources": _source_manifest(source_paths),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    DiseaseOntology.from_directory(output_dir)
    return manifest


def _load_source_file(
    path: Path,
    drafts: dict[str, _ConceptDraft],
    *,
    source_kind: str,
) -> None:
    if not path.is_file():
        raise ValueError(f"ontology source does not exist: {path}")
    suffix = path.suffix.casefold()
    if suffix == ".xml":
        if source_kind == "mesh":
            _load_mesh_xml(path, drafts)
        else:
            _load_orphanet_xml(path, drafts)
        return
    if suffix in {".yaml", ".yml"}:
        values = yaml.safe_load(path.read_text(encoding="utf-8"))
    elif suffix == ".json":
        values = json.loads(path.read_text(encoding="utf-8"))
    else:
        values = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    for value in _as_records(values):
        _merge_record(drafts, value, default_source=source_kind)


def _load_curated_aliases(path: Path, drafts: dict[str, _ConceptDraft]) -> None:
    values = yaml.safe_load(path.read_text(encoding="utf-8"))
    records = values.get("concepts", values) if isinstance(values, dict) else values
    for value in _as_records(records):
        if not isinstance(value, dict):
            raise ValueError("curated aliases must contain object records")
        concept_id = str(value.get("concept_id") or "").strip()
        if not concept_id:
            raise ValueError("curated alias record is missing concept_id")
        draft = drafts.setdefault(concept_id, _ConceptDraft(concept_id))
        if value.get("preferred_name_en"):
            draft.preferred_name_en = str(value["preferred_name_en"]).strip()
        if value.get("preferred_name_zh"):
            draft.preferred_name_zh = str(value["preferred_name_zh"]).strip()
        for alias in value.get("aliases", []):
            draft.aliases.append(_alias_value(alias, source="curated"))


def _load_mesh_xml(path: Path, drafts: dict[str, _ConceptDraft]) -> None:
    root = ET.parse(path).getroot()
    for record in root.iter():
        if _local_name(record.tag) != "DescriptorRecord":
            continue
        mesh_id = _first_text(record, "DescriptorUI")
        preferred = _first_text(record, "DescriptorName", "String")
        if not mesh_id or not preferred:
            continue
        concept_id = f"mesh:{mesh_id}"
        draft = drafts.setdefault(concept_id, _ConceptDraft(concept_id))
        draft.mesh_id = mesh_id
        draft.preferred_name_en = preferred
        draft.aliases.append(_alias_value(preferred, language="en", alias_type="preferred", source="mesh"))
        for term in record.iter():
            if _local_name(term.tag) != "Term":
                continue
            value = _first_text(term, "String")
            if value and normalize_terminology_text(value) != normalize_terminology_text(preferred):
                draft.aliases.append(_alias_value(value, language="en", alias_type="synonym", source="mesh"))


def _load_orphanet_xml(path: Path, drafts: dict[str, _ConceptDraft]) -> None:
    root = ET.parse(path).getroot()
    for record in root.iter():
        if _local_name(record.tag) != "Disorder":
            continue
        code = str(record.attrib.get("orphaCode") or "").strip()
        preferred = _first_text(record, "Name")
        if not code or not preferred:
            continue
        concept_id = f"orpha:{code}"
        draft = drafts.setdefault(concept_id, _ConceptDraft(concept_id))
        draft.orpha_code = code
        draft.preferred_name_en = draft.preferred_name_en or preferred
        draft.aliases.append(_alias_value(preferred, language="en", alias_type="preferred", source="orphanet"))
        for synonym in record.iter():
            if _local_name(synonym.tag) != "Synonym":
                continue
            value = _first_text(synonym, "")
            if value:
                draft.aliases.append(_alias_value(value, language="en", alias_type="synonym", source="orphanet"))


def _finalize_concepts(drafts: dict[str, _ConceptDraft]) -> tuple[DiseaseConcept, ...]:
    aliases_by_text: dict[str, set[str]] = {}
    for draft in drafts.values():
        for alias in draft.aliases or []:
            aliases_by_text.setdefault(normalize_terminology_text(alias["text"]), set()).add(draft.concept_id)

    concepts: list[DiseaseConcept] = []
    for concept_id in sorted(drafts):
        draft = drafts[concept_id]
        preferred_en = draft.preferred_name_en or next(
            (
                alias["text"]
                for alias in draft.aliases or []
                if alias.get("language") == "en"
            ),
            concept_id,
        )
        aliases: list[DiseaseAlias] = []
        seen_aliases: set[tuple[str, str]] = set()
        for raw_alias in sorted(
            draft.aliases or [],
            key=lambda item: (normalize_terminology_text(item["text"]), item["language"], item["text"]),
        ):
            normalized = normalize_terminology_text(raw_alias["text"])
            key = (normalized, raw_alias["language"])
            if not normalized or key in seen_aliases:
                continue
            seen_aliases.add(key)
            resolution = raw_alias.get("resolution", "automatic")
            if len(aliases_by_text.get(normalized, set())) > 1 and resolution == "automatic":
                resolution = "confirmation_required"
            if _SHORT_ALIAS.fullmatch(raw_alias["text"]) and raw_alias["text"].isupper():
                resolution = "confirmation_required"
            aliases.append(
                DiseaseAlias(
                    text=raw_alias["text"],
                    language=raw_alias["language"],
                    alias_type=raw_alias.get("alias_type", "synonym"),
                    resolution=resolution,
                    source=raw_alias.get("source", "local"),
                )
            )
        if not aliases:
            aliases.append(
                DiseaseAlias(
                    text=preferred_en,
                    language="en",
                    alias_type="preferred",
                    source="local",
                )
            )
        terms = list(draft.pubmed_terms or _derived_pubmed_terms(preferred_en, draft.mesh_id))
        concept = DiseaseConcept(
            concept_id=concept_id,
            preferred_name_en=preferred_en,
            preferred_name_zh=draft.preferred_name_zh,
            mesh_id=draft.mesh_id,
            orpha_code=draft.orpha_code,
            pubmed_terms=terms,
            aliases=aliases,
        )
        pubmed_terms_for_concept(concept)
        concepts.append(concept)
    return tuple(concepts)


def _merge_record(
    drafts: dict[str, _ConceptDraft],
    value: dict[str, Any],
    *,
    default_source: str,
) -> None:
    if not isinstance(value, dict):
        raise ValueError("ontology records must be objects")
    mesh_id = _clean_identifier(value.get("mesh_id"))
    orpha_code = _clean_identifier(value.get("orpha_code"))
    concept_id = str(value.get("concept_id") or "").strip()
    if not concept_id:
        concept_id = f"mesh:{mesh_id}" if mesh_id else f"orpha:{orpha_code}" if orpha_code else ""
    if not concept_id:
        raise ValueError("ontology record is missing concept_id")
    draft = drafts.setdefault(concept_id, _ConceptDraft(concept_id))
    draft.mesh_id = draft.mesh_id or mesh_id
    draft.orpha_code = draft.orpha_code or orpha_code
    draft.preferred_name_en = str(
        value.get("preferred_name_en") or value.get("name") or draft.preferred_name_en
    ).strip()
    draft.preferred_name_zh = str(value.get("preferred_name_zh") or draft.preferred_name_zh).strip()
    if value.get("pubmed_terms"):
        draft.pubmed_terms = [str(item) for item in value["pubmed_terms"]]
    aliases = value.get("aliases", [])
    if isinstance(aliases, (str, dict)):
        aliases = [aliases]
    for alias in aliases:
        draft.aliases.append(_alias_value(alias, source=default_source))
    if draft.preferred_name_en:
        draft.aliases.append(
            _alias_value(
                draft.preferred_name_en,
                language="en",
                alias_type="preferred",
                source=default_source,
            )
        )
    if draft.preferred_name_zh:
        draft.aliases.append(
            _alias_value(
                draft.preferred_name_zh,
                language="zh-Hans",
                alias_type="preferred",
                source="curated",
            )
        )


def _alias_value(
    value: Any,
    *,
    language: str | None = None,
    alias_type: str | None = None,
    source: str = "local",
) -> dict[str, Any]:
    if isinstance(value, dict):
        text = str(value.get("text") or value.get("alias") or "").strip()
        language = str(value.get("language") or language or "en")
        alias_type = str(value.get("alias_type") or alias_type or "synonym")
        resolution = str(value.get("resolution") or "automatic")
        source = str(value.get("source") or source)
    else:
        text = str(value or "").strip()
        language = language or ("zh-Hans" if _contains_cjk(text) else "en")
        alias_type = alias_type or "synonym"
        resolution = "automatic"
    language = {"zh": "zh-Hans", "zh_cn": "zh-Hans", "zh_tw": "zh-Hant"}.get(
        language, language
    )
    if not text:
        raise ValueError("ontology aliases must not be blank")
    return {
        "text": text,
        "language": language,
        "alias_type": alias_type,
        "resolution": resolution,
        "source": source,
    }


def _derived_pubmed_terms(preferred_name_en: str, mesh_id: str | None) -> list[str]:
    safe_name = preferred_name_en.replace('"', "'").strip()
    terms = []
    if mesh_id:
        terms.append(f'"{safe_name}"[MeSH Terms]')
    terms.append(f'"{safe_name}"[Title/Abstract]')
    return terms


def _as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if item is not None]
    if isinstance(value, dict):
        if "records" in value:
            return _as_records(value["records"])
        return [value]
    raise ValueError("ontology input must contain records")


def _first_text(element: ET.Element, *path: str) -> str:
    current = element
    for name in path:
        current = next(
            (child for child in current if _local_name(child.tag) == name),
            None,
        )
        if current is None:
            return ""
    return "".join(current.itertext()).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean_identifier(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _gzip_deterministically(data: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as stream:
        stream.write(data)
    return output.getvalue()


def _source_manifest(paths: Iterable[Path]) -> list[dict[str, str]]:
    values = [
        {
            "name": path.name,
            "license_url": DEFAULT_LICENSE_URL,
        }
        for path in sorted(paths, key=lambda item: item.name)
    ]
    return values or [{"name": "GraphMind curated input", "license_url": DEFAULT_LICENSE_URL}]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh-file", type=Path)
    parser.add_argument("--orphanet-file", type=Path)
    parser.add_argument("--zh-aliases", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ontology-version", default="local-build-1")
    parser.add_argument("--mesh-release", default="")
    parser.add_argument("--orphanet-release", default="")
    parser.add_argument("--generated-at", default=DEFAULT_GENERATED_AT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    manifest = build_ontology(
        output=args.output,
        mesh_file=args.mesh_file,
        orphanet_file=args.orphanet_file,
        zh_aliases=args.zh_aliases,
        ontology_version=args.ontology_version,
        mesh_release=args.mesh_release,
        orphanet_release=args.orphanet_release,
        generated_at=args.generated_at,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
