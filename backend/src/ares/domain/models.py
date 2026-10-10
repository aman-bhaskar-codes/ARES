from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from ares.domain.research import AnswerOutline, RunAssessment


class RunMode(StrEnum):
    QUICK = "quick"
    RESEARCH = "research"


class RunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    DISCOVERING = "discovering"
    READING = "reading"
    EXTRACTING = "extracting"
    CHECKING = "checking"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.PARTIAL, self.FAILED, self.CANCELLED}


class SupportStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONFLICTING = "conflicting"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AssessmentState(StrEnum):
    LEGACY = "legacy"
    DETERMINISTIC_EXACT = "deterministic_exact"
    HEURISTIC_SCREENED = "heuristic_screened"
    SEMANTIC_ASSESSED = "semantic_assessed"
    UNASSESSED = "unassessed"


class DocumentStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    NEEDS_OCR = "needs_ocr"
    FAILED = "failed"


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=160)


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class DateWindow(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_window(self) -> "DateWindow":
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {self.timezone}") from exc
        if self.start is not None and self.start.tzinfo is None:
            self.start = self.start.replace(tzinfo=zone)
        if self.end is not None and self.end.tzinfo is None:
            self.end = self.end.replace(tzinfo=zone)
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("date_window.start must be earlier than or equal to date_window.end")
        return self


class RunCreate(BaseModel):
    model_provider: Literal["gemini", "qwen"] | None = None
    conversation_id: UUID
    query: str = Field(min_length=2, max_length=8_000)
    mode: RunMode = RunMode.QUICK
    source_scope: list[Literal["web", "academic", "software", "documents"]] = Field(
        default_factory=lambda: ["web"], min_length=1  # type: ignore[arg-type]
    )
    date_window: DateWindow | None = None
    document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    plugins: list[str] = Field(default_factory=list)


class CitationRef(BaseModel):
    evidence_id: UUID
    label: int


class AnswerClaim(BaseModel):
    text: str
    citation_labels: list[int] = Field(min_length=1)
    support_status: SupportStatus = SupportStatus.SUPPORTED
    checker_method: str = "legacy"
    checker_version: str = "legacy"
    assessment_state: AssessmentState = AssessmentState.LEGACY
    assessment_rationale: str = ""


class FinalizedClaim(BaseModel):
    text: str
    evidence_ids: list[UUID] = Field(min_length=1)
    support_status: SupportStatus = SupportStatus.SUPPORTED
    checker_method: str = "deterministic_heuristic"
    checker_version: str = "m07-v1"
    assessment_state: AssessmentState = AssessmentState.HEURISTIC_SCREENED
    assessment_rationale: str = ""
    evidence_relations: dict[str, Literal["supports", "contradicts", "contextualizes"]] = Field(
        default_factory=dict
    )
    evidence_rationales: dict[str, str] = Field(default_factory=dict)


class AnswerBlock(BaseModel):
    id: str
    markdown: str
    citations: list[CitationRef] = Field(default_factory=list)
    claims: list[AnswerClaim] = Field(default_factory=list)
    finalized: bool = True


class SourceView(BaseModel):
    id: UUID
    title: str
    url: HttpUrl
    domain: str
    fetched_at: datetime
    extraction_method: str
    provider: str = "web"
    source_kind: Literal["web", "academic", "software", "document"] = "web"
    canonical_identifier: str | None = None
    published_at: datetime | None = None
    discovery_rank: int | None = None
    snippet: str = ""
    read_state: Literal["full", "snippet_only", "blocked"] = "full"


class EvidenceView(BaseModel):
    id: UUID
    source: SourceView
    document_version_id: UUID | None = None
    segment_id: UUID | None = None
    asset_id: UUID | None = None
    asset_name: str | None = None
    asset_mime_type: str | None = None
    locator_data: dict[str, object] | None = None
    asset_content_url: str | None = None
    text: str
    locator: str
    char_start: int | None = None
    char_end: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    support_status: SupportStatus
    captured_at: datetime
    content_hash: str


class RunSnapshot(BaseModel):
    model_provider: Literal["gemini", "qwen"] | None = None
    id: UUID
    conversation_id: UUID
    query: str
    mode: RunMode
    source_scope: list[str] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)
    plugins: list[str] = Field(default_factory=list)
    date_window: DateWindow | None = None
    deadline_at: datetime | None = None
    budget_version: str = "legacy"
    usage_ledger: dict[str, int] = Field(default_factory=dict)
    last_seq: int = 0
    status: RunStatus
    answer_blocks: list[AnswerBlock] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    related_questions: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    cancellation_requested: bool = False
    created_at: datetime
    updated_at: datetime


class EventEnvelope(BaseModel):
    schema_version: int = 2
    run_id: UUID
    seq: int
    event_type: str
    at: datetime
    payload: dict[str, object] = Field(default_factory=dict)


class SearchHit(BaseModel):
    title: str
    url: HttpUrl
    snippet: str = ""
    rank: int = Field(ge=1)
    provider: str = "searxng"
    engine: str | None = None
    source_kind: Literal["web", "academic", "software", "document"] = "web"
    canonical_identifier: str | None = None
    published_at: datetime | None = None
    # Optional provider-declared openly readable full text candidate. It is never treated as
    # evidence until ARES fetches and parses it through the same public-destination and parser
    # safety boundaries used elsewhere.
    full_text_url: HttpUrl | None = None
    full_text_mime_type: str | None = None


class FetchedDocument(BaseModel):
    source_id: UUID = Field(default_factory=uuid4)
    user_document_id: UUID | None = None
    title: str
    url: HttpUrl
    final_url: HttpUrl
    text: str
    content_hash: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extraction_method: str
    mime_type: str = "text/html"
    byte_count: int = 0
    source_kind: Literal["web", "academic", "software", "document"] = "web"
    canonical_identifier: str | None = None
    published_at: datetime | None = None
    page_map: list[dict[str, int]] = Field(default_factory=list)


class SynthesizedClaim(BaseModel):
    text: str
    evidence_ids: list[UUID] = Field(min_length=1)


class SynthesisResult(BaseModel):
    summary_markdown: str
    claims: list[SynthesizedClaim]
    gaps: list[str] = Field(default_factory=list)
    related_questions: list[str] = Field(default_factory=list)
    provider_input_tokens: int | None = Field(default=None, ge=0)
    provider_output_tokens: int | None = Field(default=None, ge=0)
    outline: AnswerOutline | None = None
    assessment: RunAssessment | None = None


class DocumentTextCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=2_000_000)
    mime_type: Literal["text/plain", "text/markdown"] = "text/plain"


class DocumentView(BaseModel):
    id: UUID
    name: str
    mime_type: str
    byte_count: int
    content_hash: str
    status: DocumentStatus = DocumentStatus.READY
    page_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
    parser_version: str | None = None
    asset_id: UUID | None = None
    lexical_ready: bool = True
    semantic_ready: bool = False
    created_at: datetime


class ExportCreate(BaseModel):
    format: Literal["markdown", "json", "html", "pdf"]


class ArtifactView(BaseModel):
    id: UUID
    run_id: UUID
    format: Literal["markdown", "json", "html", "pdf"]
    file_name: str
    content_type: str
    byte_count: int
    content_hash: str
    download_url: str
    created_at: datetime


class ClaimEvidenceRelationView(BaseModel):
    claim_id: UUID
    claim_text: str
    evidence_id: UUID
    relation: Literal["supports", "contradicts", "contextualizes"]
    rationale: str = ""
    checker_method: str = "legacy"
    checker_version: str = "legacy"


class RunFacetView(BaseModel):
    facet_key: str
    status: Literal["supported", "conflicting", "missing"]
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    conflicting_evidence_ids: list[UUID] = Field(default_factory=list)
    independent_origin_count: int = 0
    rationale: str = ""
    checker_method: str = "deterministic"
    checker_version: str = "m10-v1"


class RunQualityView(BaseModel):
    run_id: UUID
    claim_count: int
    evidence_count: int
    source_count: int
    distinct_source_group_count: int
    citation_resolution_rate: float
    claim_citation_rate: float
    supported_claim_rate: float
    support_counts: dict[str, int] = Field(default_factory=dict)
    evidence_relation_counts: dict[str, int] = Field(default_factory=dict)
    evidence_relations: list[ClaimEvidenceRelationView] = Field(default_factory=list)
    facets: list[RunFacetView] = Field(default_factory=list)
    source_kind_counts: dict[str, int] = Field(default_factory=dict)
    provider_counts: dict[str, int] = Field(default_factory=dict)
    risky_source_events: int = 0
    duplicate_sources_removed: int = 0
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)
    queue_wait_ms: float | None = None
    run_elapsed_ms: float | None = None
    gaps_count: int = 0
    confidence_extraction: float | None = None
    confidence_relevance: float | None = None
    confidence_support: float | None = None


class AuthMeView(BaseModel):
    user_id: UUID
    workspace_id: UUID
    role: str
    subject: str
    email: str | None = None
    display_name: str | None = None
    auth_mode: str
    csrf_required: bool


class WorkspaceView(BaseModel):
    id: UUID
    name: str
    role: str


class WorkspaceSwitchRequest(BaseModel):
    workspace_id: UUID


class WorkerFleetView(BaseModel):
    total: int
    active: int
    draining: int
    stale: int
