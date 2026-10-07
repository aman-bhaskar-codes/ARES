from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    subject: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class WorkspaceRow(Base):
    __tablename__ = "workspaces"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class WorkspaceMembershipRow(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(24), default="viewer")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OidcStateRow(Base):
    __tablename__ = "oidc_states"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_verifier: Mapped[str] = mapped_column(String(256))
    nonce: Mapped[str] = mapped_column(String(256))
    return_path: Mapped[str] = mapped_column(String(1024), default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True, nullable=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    action: Mapped[str] = mapped_column(String(96), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class WorkerInstanceRow(Base):
    __tablename__ = "worker_instances"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    instance_name: Mapped[str] = mapped_column(String(160))
    state: Mapped[str] = mapped_column(String(24), default="starting", index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capabilities_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class ConversationRow(Base):
    __tablename__ = "conversations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(160), default="New research")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(24))
    source_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    document_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    date_window: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    budget_version: Mapped[str] = mapped_column(String(32), default="m07-v1")
    usage_ledger: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True)
    answer_blocks: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    outline: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    assessment: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    leased_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    lease_token: Mapped[UUID | None] = mapped_column(nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RunStepRow(Base):
    __tablename__ = "run_steps"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "step_key", "input_hash", "schema_version", name="uq_run_step_identity"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    step_key: Mapped[str] = mapped_column(String(96), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="started", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    lease_token: Mapped[UUID | None] = mapped_column(nullable=True)
    output_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResourceLeaseRow(Base):
    __tablename__ = "resource_leases"
    __table_args__ = (UniqueConstraint("resource_key", "slot", name="uq_resource_lease_slot"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    owner_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    resource_key: Mapped[str] = mapped_column(String(96), index=True)
    slot: Mapped[int] = mapped_column(Integer)
    lease_token: Mapped[UUID] = mapped_column(index=True)
    leased_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SourceRow(Base):
    __tablename__ = "sources"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(64), default="web")
    source_kind: Mapped[str] = mapped_column(String(32), default="web", index=True)
    canonical_identifier: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovery_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    extraction_method: Mapped[str] = mapped_column(String(80))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    origin_group_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    extraction_method: Mapped[str] = mapped_column(String(80))
    mime_type: Mapped[str] = mapped_column(String(120), default="text/html")
    byte_count: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    page_map: Mapped[list[dict[str, int]]] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    segment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence_segments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(255))
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    support_status: Mapped[str] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[SourceRow] = relationship(lazy="joined")


class ClaimRow(Base):
    __tablename__ = "claims"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    support_status: Mapped[str] = mapped_column(String(40), default="supported")
    checker_method: Mapped[str] = mapped_column(String(64), default="legacy")
    checker_version: Mapped[str] = mapped_column(String(32), default="legacy")
    assessment_state: Mapped[str] = mapped_column(String(32), default="legacy")
    assessment_rationale: Mapped[str] = mapped_column(Text, default="")


class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (UniqueConstraint("claim_id", "evidence_id", name="uq_claim_evidence_pair"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(32), default="supports")
    rationale: Mapped[str] = mapped_column(Text, default="")
    checker_method: Mapped[str] = mapped_column(String(64), default="legacy")
    checker_version: Mapped[str] = mapped_column(String(32), default="legacy")


class ResearchCacheRow(Base):
    __tablename__ = "research_cache"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "namespace",
            "cache_key",
            "policy_version",
            name="uq_research_cache_identity",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    namespace: Mapped[str] = mapped_column(String(64), index=True)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(32), default="m10-v1")
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class FacetCoverageRow(Base):
    __tablename__ = "facet_coverage"
    __table_args__ = (UniqueConstraint("run_id", "facet_key", name="uq_facet_coverage_run_key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    facet_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), default="missing", index=True)
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    conflicting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text, default="")
    checker_method: Mapped[str] = mapped_column(String(64), default="deterministic")
    checker_version: Mapped[str] = mapped_column(String(32), default="m10-v1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class VisualizationDatasetRow(Base):
    __tablename__ = "visualization_datasets"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "dataset_kind", "content_hash", name="uq_visualization_dataset_content"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    dataset_kind: Mapped[str] = mapped_column(String(40), index=True)
    dataset_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    lineage_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class VisualizationRow(Base):
    __tablename__ = "visualizations"
    __table_args__ = (
        UniqueConstraint("run_id", "kind", "spec_hash", name="uq_visualization_spec"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("visualization_datasets.id", ondelete="CASCADE"), index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    approved_spec_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    spec_hash: Mapped[str] = mapped_column(String(64), index=True)
    export_metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class UserDocumentRow(Base):
    __tablename__ = "user_documents"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    byte_count: Mapped[int] = mapped_column(Integer)
    blob_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_map: Mapped[list[dict[str, int]]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    parser_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    asset_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    lexical_ready: Mapped[bool] = mapped_column(Boolean, default=True)
    semantic_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DocumentChunkRow(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator: Mapped[str] = mapped_column(String(255))
    evidence_segment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence_segments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    parent_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    previous_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    next_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DocumentEmbeddingRow(Base):
    __tablename__ = "document_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_id", "dimensions", name="uq_chunk_embedding_identity"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("retrieval_profiles.id", ondelete="CASCADE"), index=True, nullable=True
    )
    model_id: Mapped[str] = mapped_column(String(160), index=True)
    dimensions: Mapped[int] = mapped_column(Integer)
    vector_json: Mapped[list[float]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AssetVersionRow(Base):
    __tablename__ = "asset_versions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    original_blob_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(120), index=True)
    byte_count: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="quarantined", index=True)
    cloud_media_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    media_metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ExtractionVersionRow(Base):
    __tablename__ = "extraction_versions"
    __table_args__ = (
        UniqueConstraint(
            "asset_version_id",
            "parser_id",
            "parser_revision",
            "config_hash",
            name="uq_extraction_version_identity",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), index=True
    )
    parser_id: Mapped[str] = mapped_column(String(80))
    parser_revision: Mapped[str] = mapped_column(String(80))
    model_revision: Mapped[str | None] = mapped_column(String(160), nullable=True)
    config_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="processing", index=True)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_map: Mapped[list[dict[str, int]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvidenceSegmentRow(Base):
    __tablename__ = "evidence_segments"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    extraction_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_versions.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_documents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    modality: Mapped[str] = mapped_column(String(24), index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator_json: Mapped[dict[str, object]] = mapped_column(JSON)
    derivation_kind: Mapped[str] = mapped_column(String(64), default="machine_extracted")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    origin_group_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DocumentTableRow(Base):
    __tablename__ = "document_tables"
    __table_args__ = (
        UniqueConstraint("extraction_version_id", "table_key", name="uq_document_table_key"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    extraction_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_versions.id", ondelete="CASCADE"), index=True
    )
    table_key: Mapped[str] = mapped_column(String(120))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    rows: Mapped[int] = mapped_column(Integer)
    columns: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DocumentTableCellRow(Base):
    __tablename__ = "document_table_cells"
    __table_args__ = (
        UniqueConstraint("table_id", "row_index", "column_index", name="uq_document_table_cell"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    table_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_tables.id", ondelete="CASCADE"), index=True
    )
    segment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("evidence_segments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    row_index: Mapped[int] = mapped_column(Integer)
    column_index: Mapped[int] = mapped_column(Integer)
    row_span: Mapped[int] = mapped_column(Integer, default=1)
    column_span: Mapped[int] = mapped_column(Integer, default=1)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_value_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_header: Mapped[bool] = mapped_column(Boolean, default=False)
    locator_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class AssetRenditionRow(Base):
    __tablename__ = "asset_renditions"
    __table_args__ = (
        UniqueConstraint("asset_version_id", "kind", "content_hash", name="uq_asset_rendition"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), index=True
    )
    extraction_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extraction_versions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String(64))
    blob_key: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(120))
    byte_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class MediaTrackRow(Base):
    __tablename__ = "media_tracks"
    __table_args__ = (
        UniqueConstraint(
            "asset_version_id", "track_type", "stream_index", name="uq_media_track_identity"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), index=True
    )
    extraction_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extraction_versions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    track_type: Mapped[str] = mapped_column(String(16), index=True)
    stream_index: Mapped[int] = mapped_column(Integer)
    codec_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_frame_rate: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class MediaFrameRow(Base):
    __tablename__ = "media_frames"
    __table_args__ = (
        UniqueConstraint(
            "asset_version_id",
            "presentation_time_ms",
            "content_hash",
            name="uq_media_frame_identity",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), index=True
    )
    extraction_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extraction_versions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    rendition_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_renditions.id", ondelete="CASCADE"), index=True
    )
    presentation_time_ms: Mapped[int] = mapped_column(Integer, index=True)
    source_kind: Mapped[str] = mapped_column(String(24))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_documents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    lexical_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    semantic_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionEventRow(Base):
    __tablename__ = "ingestion_events"
    __table_args__ = (UniqueConstraint("ingestion_id", "seq", name="uq_ingestion_event_seq"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    ingestion_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class EmbeddingProfileRow(Base):
    __tablename__ = "embedding_profiles"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(160))
    model_revision: Mapped[str] = mapped_column(String(160))
    dimensions: Mapped[int] = mapped_column(Integer)
    normalization: Mapped[str] = mapped_column(String(40), default="l2")
    pooling: Mapped[str] = mapped_column(String(40), default="model_default")
    query_prefix: Mapped[str] = mapped_column(String(80), default="")
    passage_prefix: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )



class RetrievalProfileRow(Base):
    __tablename__ = "retrieval_profiles"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(160))
    artifact_digest: Mapped[str] = mapped_column(String(160))
    tokenizer_version: Mapped[str] = mapped_column(String(80))
    dimensions: Mapped[int] = mapped_column(Integer)
    distance_metric: Mapped[str] = mapped_column(String(40), default="cosine")
    language_coverage: Mapped[str] = mapped_column(String(80), default="en")
    chunk_policy: Mapped[str] = mapped_column(String(120))
    extraction_revision: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    format: Mapped[str] = mapped_column(String(24))
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    blob_key: Mapped[str] = mapped_column(Text)
    byte_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ProviderQuotaLockRow(Base):
    __tablename__ = "provider_quota_locks"
    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    touched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ProviderUsageRow(Base):
    __tablename__ = "provider_usage"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    requests: Mapped[int] = mapped_column(Integer, default=1)
    input_tokens_reserved: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens_reserved: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_reserved: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class RetrievalTraceRow(Base):
    __tablename__ = "retrieval_traces"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    query_hash: Mapped[str]
    profile_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("retrieval_profiles.id", ondelete="CASCADE"), index=True
    )
    filters: Mapped[dict] = mapped_column(sa.JSON)
    candidate_ids: Mapped[list[UUID]] = mapped_column(sa.JSON)
    candidate_ranks: Mapped[list[float]] = mapped_column(sa.JSON)
    selected_packet_ids: Mapped[list[UUID]] = mapped_column(sa.JSON)
    stage_times: Mapped[dict] = mapped_column(sa.JSON)
    cache_freshness: Mapped[str]
    coverage_gaps: Mapped[list[str]] = mapped_column(sa.JSON)
    policy_revision: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

def default_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite+pysqlite:///./.data/ares-dev.sqlite3")


class TenantSession(Session):
    """Session that binds the current request tenant into PostgreSQL transactions.

    PostgreSQL RLS policies read these transaction-local settings. Worker connections use
    a dedicated BYPASSRLS role and therefore do not depend on request context.
    """


@event.listens_for(TenantSession, "after_begin")
def _bind_rls_context(session: Session, transaction, connection) -> None:  # type: ignore[no-untyped-def]
    if connection.dialect.name != "postgresql":
        return
    from ares.application.identity import current_principal

    principal = current_principal()
    connection.execute(
        text(
            "SELECT set_config('app.workspace_id', :workspace_id, true), "
            "set_config('app.user_id', :user_id, true)"
        ),
        {
            "workspace_id": str(principal.workspace_id) if principal is not None else "",
            "user_id": str(principal.user_id) if principal is not None else "",
        },
    )


def build_session_factory(database_url: str | None = None):
    url = database_url or default_database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, class_=TenantSession)
