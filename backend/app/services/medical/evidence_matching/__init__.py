"""Local, evidence-preserving matching between medical findings and PubMed results."""

from app.services.medical.evidence_matching.finding_extractor import (
    FindingExtractionError,
    FindingExtractor,
    extract_matchable_findings,
)
from app.services.medical.evidence_matching.matcher import (
    LiteratureCandidateMatcher,
    match_articles,
)
from app.services.medical.evidence_matching.models import (
    FindingMatchResult,
    LiteratureMatchResult,
    MatchFeature,
    MatchableFinding,
    StudyCard,
)
from app.services.medical.evidence_matching.study_card_builder import (
    StudyCardBuilder,
    build_study_card,
)

__all__ = [
    "FindingExtractionError",
    "FindingExtractor",
    "FindingMatchResult",
    "LiteratureCandidateMatcher",
    "LiteratureMatchResult",
    "MatchFeature",
    "MatchableFinding",
    "StudyCard",
    "StudyCardBuilder",
    "build_study_card",
    "extract_matchable_findings",
    "match_articles",
]
