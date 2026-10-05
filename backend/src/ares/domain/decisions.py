from __future__ import annotations

from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field

from ares.domain.models import AssessmentState


class ResearchTask(StrEnum):
    EXPLANATION = "explanation"
    COMPARISON = "comparison"
    CURRENT = "current_events"
    LITERATURE = "literature"
    SOFTWARE = "software"
    DOCUMENT = "document"


class ClaimVerdict(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partially_supported"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient_evidence"


class RouteDecision(BaseModel):
    task: ResearchTask = ResearchTask.EXPLANATION
    needs_academic: bool = False
    needs_software: bool = False
    needs_current_web: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provider: str = "deterministic"


class FacetStatus(StrEnum):
    SUPPORTED = "supported"
    CONFLICTING = "conflicting"
    MISSING = "missing"


class FacetAssessment(BaseModel):
    facet: str
    status: FacetStatus
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    conflicting_evidence_ids: list[UUID] = Field(default_factory=list)
    rationale: str = ""


class CoverageDecision(BaseModel):
    sufficient: bool
    confidence: float = Field(ge=0.0, le=1.0)
    missing_facets: list[str] = Field(default_factory=list)
    facets: list[FacetAssessment] = Field(default_factory=list)
    provider: str = "deterministic"


class ClaimDecision(BaseModel):
    verdict: ClaimVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    provider: str = "deterministic"
    checker_method: str = "deterministic_heuristic"
    checker_version: str = "m07-v1"
    assessment_state: AssessmentState = AssessmentState.HEURISTIC_SCREENED
    rationale: str = ""
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    conflicting_evidence_ids: list[UUID] = Field(default_factory=list)
