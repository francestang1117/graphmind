"""Contracts for the public disease exploration guide.

The guide is intentionally separate from disease profiles. Profiles contain
workspace-owned paper evidence; guides contain reviewed, public knowledge.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


GuideEvidenceStatus = Literal["established", "clinical_research", "early_exploration"]
GuideRegionStatus = Literal["verified", "not_verified"]
GuideStatus = Literal["available", "preparing"]


class DiseaseGuideSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    organization: str = Field(min_length=1, max_length=160)
    url: HttpUrl
    published_at: date | None = None
    checked_at: date
    source_type: Literal["institutional", "regulatory", "clinical_registry", "reference"]
    language: str = Field(default="", max_length=16)
    usage_note: str = Field(default="", max_length=600)


class DiseaseGuideText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def source_ids_are_unique(self) -> "DiseaseGuideText":
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("source_ids must not contain duplicates")
        return self


class DiseaseGuideResearchContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_kind: Literal["registry", "published_results", "review"]
    goal: DiseaseGuideText
    current: DiseaseGuideText
    unknown: DiseaseGuideText


class DiseaseGuidePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1200)
    question: str = Field(default="", max_length=240)
    explanation: DiseaseGuideText | None = None
    qualifier: str = Field(default="", max_length=800)
    evidence_status: GuideEvidenceStatus
    evidence_stage: str = Field(default="", max_length=240)
    applicability: str = Field(default="", max_length=800)
    region: str = Field(default="", max_length=40)
    source_ids: list[str] = Field(min_length=1, max_length=8)
    research_context: DiseaseGuideResearchContext | None = None

    @model_validator(mode="after")
    def validate_source_ids(self) -> "DiseaseGuidePoint":
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("source_ids must not contain duplicates")
        if self.evidence_status != "established" and not self.evidence_stage:
            raise ValueError("research points must declare evidence_stage")
        if self.explanation:
            missing = sorted(set(self.explanation.source_ids) - set(self.source_ids))
            if missing:
                raise ValueError(
                    "explanation sources must be included in point source_ids: "
                    + ", ".join(missing)
                )
        if self.research_context:
            context_source_ids = {
                source_id
                for claim in (
                    self.research_context.goal,
                    self.research_context.current,
                    self.research_context.unknown,
                )
                for source_id in claim.source_ids
            }
            missing = sorted(context_source_ids - set(self.source_ids))
            if missing:
                raise ValueError(
                    "research context sources must be included in point source_ids: "
                    + ", ".join(missing)
                )
        return self


class DiseaseGuideTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    definition: DiseaseGuideText
    context: DiseaseGuideText | None = None


class DiseaseGuideTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=240)
    summary: DiseaseGuideText
    key_points: list[DiseaseGuidePoint] = Field(min_length=1, max_length=8)
    terms: list[DiseaseGuideTerm] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_topic_scope(self) -> "DiseaseGuideTopic":
        if self.id == "treatments":
            for point in self.key_points:
                if not point.region:
                    raise ValueError("treatment points must declare a checked region")
                if not point.evidence_stage:
                    raise ValueError("treatment points must declare an evidence stage")
        if len({point.id for point in self.key_points}) != len(self.key_points):
            raise ValueError("topic point ids must be unique")
        if len({term.id for term in self.terms}) != len(self.terms):
            raise ValueError("topic term ids must be unique")
        return self


class DiseaseGuide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["disease-guide-v1"] = "disease-guide-v1"
    concept_id: str = Field(min_length=1, max_length=120)
    language: Literal["zh-CN", "en"]
    region: str = Field(min_length=2, max_length=40)
    region_status: GuideRegionStatus = "verified"
    region_note: str = Field(default="", max_length=800)
    reviewed_at: date
    title: str = Field(min_length=1, max_length=160)
    preferred_name_en: str = Field(min_length=1, max_length=160)
    preferred_name_zh: str = Field(min_length=1, max_length=160)
    overview: DiseaseGuideText
    topics: list[DiseaseGuideTopic] = Field(min_length=1, max_length=8)
    sources: list[DiseaseGuideSource] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_source_references(self) -> "DiseaseGuide":
        source_ids = {source.id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("source ids must be unique")

        references = list(self.overview.source_ids)
        for topic in self.topics:
            references.extend(topic.summary.source_ids)
            for term in topic.terms:
                references.extend(term.definition.source_ids)
                if term.context:
                    references.extend(term.context.source_ids)
            for point in topic.key_points:
                references.extend(point.source_ids)
                if point.explanation:
                    references.extend(point.explanation.source_ids)
                if point.research_context:
                    references.extend(
                        source_id
                        for claim in (
                            point.research_context.goal,
                            point.research_context.current,
                            point.research_context.unknown,
                        )
                        for source_id in claim.source_ids
                    )
        missing = sorted(set(references) - source_ids)
        if missing:
            raise ValueError(f"guide references unknown sources: {', '.join(missing)}")

        topic_ids = [topic.id for topic in self.topics]
        if len(topic_ids) != len(set(topic_ids)):
            raise ValueError("topic ids must be unique")
        return self


class DiseaseGuideSearchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: str
    preferred_name_en: str
    preferred_name_zh: str
    matched_alias: str | None = None
    guide_status: GuideStatus
    guide_languages: list[str] = Field(default_factory=list)


class DiseaseGuideSearchView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DiseaseGuideSearchItem]
