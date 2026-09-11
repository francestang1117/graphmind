"""Versioned, local medical terminology used by safe literature queries."""

from app.services.medical.terminology.loader import (
    DiseaseOntology,
    DiseaseOntologyError,
    get_default_ontology,
)
from app.services.medical.terminology.matcher import (
    DiseaseMatchError,
    DiseaseMatcher,
    OntologyResolution,
)
from app.services.medical.terminology.models import (
    ConceptSelection,
    DiseaseAlias,
    DiseaseCandidate,
    DiseaseConcept,
    DiseaseMatch,
    OntologyManifest,
)

__all__ = [
    "ConceptSelection",
    "DiseaseAlias",
    "DiseaseCandidate",
    "DiseaseConcept",
    "DiseaseMatch",
    "DiseaseMatchError",
    "DiseaseOntology",
    "DiseaseOntologyError",
    "DiseaseMatcher",
    "OntologyManifest",
    "OntologyResolution",
    "get_default_ontology",
]
