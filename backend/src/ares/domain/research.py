from __future__ import annotations

from datetime import datetime, UTC
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator, HttpUrl


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2_000)
    limit: int = Field(default=8, ge=1, le=20)
    language: str = "all"
    time_range: Literal["day", "week", "month", "year"] | None = None
    published_after: datetime | None = None
    published_before: datetime | None = None
    timezone: str = "UTC"
    timeout_seconds: float | None = Field(default=None, gt=0, le=120)


class ResearchPlan(BaseModel):
    query_variants: list[str] = Field(min_length=1, max_length=8)
    facets: list[str] = Field(default_factory=list, max_length=12)
    language: str = "all"
    time_range: Literal["day", "week", "month", "year"] | None = None
    intent: Literal["exact", "narrow", "comparison", "multi-hop", "temporal", "analysis"] = "narrow"
    subqueries: list[str] = Field(default_factory=list, max_length=3)

    from pydantic import model_validator
    @model_validator(mode="after")
    def _default_subqueries(self) -> ResearchPlan:
        if not self.subqueries:
            self.subqueries = self.query_variants[:3]
        return self


class EvidenceCandidate(BaseModel):
    candidate_id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    title: str
    url: HttpUrl
    text: str
    locator: str
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    lexical_score: float = 0.0
    semantic_score: float | None = None
    combined_score: float = 0.0
    page_start: int | None = None
    page_end: int | None = None
    segment_id: UUID | None = None


class EvidencePacket(BaseModel):
    evidence_id: UUID
    source_id: UUID
    origin_group_id: UUID | None = None
    title: str
    url: HttpUrl
    domain: str
    text: str
    locator: str
    captured_at: datetime
    content_hash: str


class PersistedEvidence(BaseModel):
    source_id: UUID
    document_version_id: UUID
    evidence_id: UUID

class RetrievalProfile(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    profile_key: str
    provider: str
    model_id: str
    artifact_digest: str
    tokenizer_version: str
    dimensions: int = Field(gt=0)
    distance_metric: str = "cosine"
    language_coverage: str = "en"
    chunk_policy: str
    extraction_revision: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class RetrievalTrace(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    query_hash: str
    profile_id: UUID
    filters: dict
    candidate_ids: list[UUID]
    candidate_ranks: list[float]
    selected_packet_ids: list[UUID]
    stage_times: dict[str, float]
    cache_freshness: str
    coverage_gaps: list[str]
    policy_revision: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

class ClaimProposal(BaseModel):
    claim: str
    evidence_ids: list[UUID]

class AnswerOutline(BaseModel):
    sections: list[str]
    facets: list[str]
    claims: list[ClaimProposal]

class RunAssessment(BaseModel):
    method: str
    version: str
    rationale: str
    relations: dict[str, list[UUID]]
    confidence_extraction: float
    confidence_relevance: float
    confidence_support: float
