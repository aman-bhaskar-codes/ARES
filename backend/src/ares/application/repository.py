from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ares.adapters.db import (
    AssetRenditionRow,
    AssetVersionRow,
    ArtifactRow,
    ClaimEvidenceRow,
    ClaimRow,
    ConversationRow,
    DocumentChunkRow,
    DocumentEmbeddingRow,
    DocumentTableCellRow,
    DocumentTableRow,
    DocumentVersionRow,
    EvidenceRow,
    EvidenceSegmentRow,
    ExtractionVersionRow,
    IngestionEventRow,
    IngestionJobRow,
    MediaFrameRow,
    MediaTrackRow,
    JobRow,
    ProviderQuotaLockRow,
    ResearchCacheRow,
    FacetCoverageRow,
    ProviderUsageRow,
    ResourceLeaseRow,
    RunEventRow,
    RunRow,
    RunStepRow,
    SourceRow,
    UserDocumentRow,
    UserRow,
    WorkspaceRow,
    WorkspaceMembershipRow,
    WorkerInstanceRow,
    VisualizationDatasetRow,
    VisualizationRow,
)
from ares.domain.assets import (
    AssetStatus,
    AssetView,
    EvidenceLocator,
    ExtractionSegmentDraft,
    ExtractionTableDraft,
    IngestionEventEnvelope,
    IngestionStage,
    IngestionStatus,
    IngestionView,
    MediaFrameDraft,
    MediaFrameView,
    MediaStoryboardView,
    MediaTrackDraft,
    MediaTrackView,
    SegmentView,
    TableCellView,
    TableView,
)
from ares.domain.models import (
    AnswerClaim,
    AnswerBlock,
    CitationRef,
    ConversationView,
    EventEnvelope,
    EvidenceView,
    ArtifactView,
    DocumentStatus,
    DocumentTextCreate,
    DocumentView,
    FetchedDocument,
    FinalizedClaim,
    RunCreate,
    ClaimEvidenceRelationView,
    RunFacetView,
    RunQualityView,
    RunMode,
    RunSnapshot,
    RunStatus,
    SourceView,
    SupportStatus,
)
from ares.domain.research import EvidenceCandidate, EvidencePacket
from ares.domain.visualizations import (
    NumericTablePointCandidate,
    VisualizationDraft,
    VisualizationLineageRef,
    VisualizationSpec,
    VisualizationView,
    validate_visualization_dataset,
)
from ares.application.documents import PreparedChunk
from ares.application.source_identity import source_origin_group
from ares.application.identity import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Principal,
    WorkspaceRole,
    current_principal,
    local_principal,
)
from ares.domain.state_machine import assert_transition
from ares.domain.budgets import BUDGETS, BUDGET_VERSION


class NotFoundError(LookupError):
    pass


class IdempotencyConflictError(ValueError):
    pass


class StaleLeaseError(RuntimeError):
    pass


class QuotaExceededError(RuntimeError):
    pass


class RunAdmissionError(RuntimeError):
    pass


class RunBudgetExceededError(RuntimeError):
    pass


class RunAuthorizationError(RuntimeError):
    pass


class ResourceCapacityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JobLease:
    run_id: UUID
    token: UUID
    leased_until: datetime
    attempt: int


@dataclass(frozen=True, slots=True)
class ResourceLease:
    run_id: UUID
    resource_key: str
    slot: int
    token: UUID
    leased_until: datetime


@dataclass(frozen=True, slots=True)
class IngestionLease:
    ingestion_id: UUID
    asset_id: UUID
    token: UUID
    leased_until: datetime
    attempt: int


@dataclass(frozen=True, slots=True)
class IngestionPublication:
    document_id: UUID
    extraction_version_id: UUID


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class Repository:
    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions
        self._event_lock = threading.RLock()

    @property
    def dialect_name(self) -> str:
        bind = self._sessions.kw.get("bind")
        return bind.dialect.name if bind is not None else "unknown"

    @staticmethod
    def _request_principal() -> Principal:
        return current_principal() or local_principal()

    @staticmethod
    def _visible_workspace_id() -> UUID | None:
        principal = current_principal()
        return principal.workspace_id if principal is not None else None

    @staticmethod
    def _ensure_local_identity(session: Session, principal: Principal) -> None:
        if principal.user_id != SYSTEM_USER_ID or principal.workspace_id != SYSTEM_WORKSPACE_ID:
            return
        if session.get(UserRow, SYSTEM_USER_ID) is None:
            session.add(
                UserRow(
                    id=SYSTEM_USER_ID,
                    subject="local:system",
                    display_name="Local ARES",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        if session.get(WorkspaceRow, SYSTEM_WORKSPACE_ID) is None:
            session.add(
                WorkspaceRow(
                    id=SYSTEM_WORKSPACE_ID, name="Local workspace", created_at=datetime.now(UTC)
                )
            )
        session.flush()
        membership = session.scalar(
            select(WorkspaceMembershipRow).where(
                WorkspaceMembershipRow.workspace_id == SYSTEM_WORKSPACE_ID,
                WorkspaceMembershipRow.user_id == SYSTEM_USER_ID,
            )
        )
        if membership is None:
            session.add(
                WorkspaceMembershipRow(
                    workspace_id=SYSTEM_WORKSPACE_ID,
                    user_id=SYSTEM_USER_ID,
                    role=WorkspaceRole.OWNER.value,
                    created_at=datetime.now(UTC),
                )
            )
            session.flush()

    def _run_row(self, session: Session, run_id: UUID) -> RunRow | None:
        stmt = select(RunRow).where(RunRow.id == run_id)
        workspace_id = self._visible_workspace_id()
        if workspace_id is not None:
            stmt = stmt.where(RunRow.workspace_id == workspace_id)
        return session.scalar(stmt)

    def _conversation_row(self, session: Session, conversation_id: UUID) -> ConversationRow | None:
        stmt = select(ConversationRow).where(ConversationRow.id == conversation_id)
        workspace_id = self._visible_workspace_id()
        if workspace_id is not None:
            stmt = stmt.where(ConversationRow.workspace_id == workspace_id)
        return session.scalar(stmt)

    def create_conversation(self, title: str | None = None) -> ConversationView:
        principal = self._request_principal()
        with self._sessions.begin() as session:
            self._ensure_local_identity(session, principal)
            row = ConversationRow(
                workspace_id=principal.workspace_id,
                created_by_user_id=principal.user_id,
                title=(title or "New research").strip() or "New research",
            )
            session.add(row)
            session.flush()
            return ConversationView.model_validate(row)

    def list_conversations(self, limit: int = 50) -> list[ConversationView]:
        with self._sessions() as session:
            stmt = select(ConversationRow)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(ConversationRow.workspace_id == workspace_id)
            rows = session.scalars(
                stmt.order_by(ConversationRow.updated_at.desc()).limit(limit)
            ).all()
            return [ConversationView.model_validate(row) for row in rows]

    def create_run(
        self,
        request: RunCreate,
        idempotency_key: str,
        *,
        max_active_runs: int | None = None,
        max_active_runs_per_workspace: int | None = None,
        max_active_runs_per_user: int | None = None,
    ) -> tuple[RunSnapshot, bool]:
        request_hash = _hash_request(request)
        principal = self._request_principal()
        scoped_key = hashlib.sha256(
            f"{principal.workspace_id}\0{idempotency_key}".encode("utf-8")
        ).hexdigest()
        with self._sessions.begin() as session:
            self._ensure_local_identity(session, principal)
            conversation = session.scalar(
                select(ConversationRow).where(
                    ConversationRow.id == request.conversation_id,
                    ConversationRow.workspace_id == principal.workspace_id,
                )
            )
            if conversation is None:
                raise NotFoundError("conversation not found")
            if request.document_ids:
                owned_documents = set(
                    session.scalars(
                        select(UserDocumentRow.id).where(
                            UserDocumentRow.id.in_(request.document_ids),
                            UserDocumentRow.workspace_id == principal.workspace_id,
                        )
                    ).all()
                )
                missing = [
                    document_id
                    for document_id in request.document_ids
                    if document_id not in owned_documents
                ]
                if missing:
                    raise NotFoundError(f"document not found: {missing[0]}")
            existing = session.scalar(
                select(RunRow).where(
                    RunRow.idempotency_key == scoped_key,
                    RunRow.workspace_id == principal.workspace_id,
                )
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        "idempotency key reused with a different request"
                    )
                return self._snapshot(existing), False

            terminal = [
                RunStatus.COMPLETED.value,
                RunStatus.PARTIAL.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
            ]
            if any(
                v is not None
                for v in (max_active_runs, max_active_runs_per_workspace, max_active_runs_per_user)
            ):
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 1095914835})
                if max_active_runs is not None:
                    if session.bind is not None and session.bind.dialect.name == "postgresql":
                        global_active = int(
                            session.scalar(text("SELECT ares_global_active_run_count()")) or 0
                        )
                    else:
                        global_active = int(
                            session.scalar(
                                select(func.count())
                                .select_from(RunRow)
                                .where(RunRow.status.not_in(terminal))
                            )
                            or 0
                        )
                    if global_active >= max_active_runs:
                        raise RunAdmissionError(
                            f"global active run limit reached ({max_active_runs})"
                        )
                if max_active_runs_per_workspace is not None:
                    workspace_active = int(
                        session.scalar(
                            select(func.count())
                            .select_from(RunRow)
                            .where(
                                RunRow.workspace_id == principal.workspace_id,
                                RunRow.status.not_in(terminal),
                            )
                        )
                        or 0
                    )
                    if workspace_active >= max_active_runs_per_workspace:
                        raise RunAdmissionError(
                            f"workspace active run limit reached ({max_active_runs_per_workspace})"
                        )
                if max_active_runs_per_user is not None:
                    user_active = int(
                        session.scalar(
                            select(func.count())
                            .select_from(RunRow)
                            .where(
                                RunRow.workspace_id == principal.workspace_id,
                                RunRow.created_by_user_id == principal.user_id,
                                RunRow.status.not_in(terminal),
                            )
                        )
                        or 0
                    )
                    if user_active >= max_active_runs_per_user:
                        raise RunAdmissionError(
                            f"user active run limit reached ({max_active_runs_per_user})"
                        )

            now = datetime.now(UTC)
            budget = BUDGETS[request.mode]
            run = RunRow(
                conversation_id=request.conversation_id,
                workspace_id=principal.workspace_id,
                created_by_user_id=principal.user_id,
                query=request.query,
                mode=request.mode.value,
                source_scope=list(request.source_scope),
                document_ids=[str(value) for value in request.document_ids],
                date_window=request.date_window.model_dump(mode="json")
                if request.date_window
                else None,
                deadline_at=now + timedelta(seconds=budget.wall_clock_seconds),
                budget_version=BUDGET_VERSION,
                usage_ledger={},
                last_seq=1,
                status=RunStatus.QUEUED.value,
                idempotency_key=scoped_key,
                request_hash=request_hash,
                created_at=now,
                updated_at=now,
            )
            session.add(run)
            session.flush()
            session.add(JobRow(run_id=run.id))
            session.add(
                RunEventRow(
                    run_id=run.id,
                    seq=1,
                    schema_version=2,
                    event_type="run.created",
                    payload={
                        "status": "queued",
                        "budget_version": BUDGET_VERSION,
                        "deadline_at": run.deadline_at.isoformat(),
                    },
                )
            )
            conversation.updated_at = datetime.now(UTC)
            session.flush()
            return self._snapshot(run), True

    def get_run(self, run_id: UUID) -> RunSnapshot:
        with self._sessions() as session:
            row = self._run_row(session, run_id)
            if row is None:
                raise NotFoundError("run not found")
            return self._snapshot(row)

    def initialize_run_execution_contract(
        self, run_id: UUID, *, wall_clock_seconds: int, lease_token: UUID
    ) -> RunSnapshot:
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            row = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if row is None:
                raise NotFoundError("run not found")
            if row.deadline_at is None:
                row.deadline_at = datetime.now(UTC) + timedelta(seconds=wall_clock_seconds)
            if not row.budget_version or row.budget_version == "legacy":
                row.budget_version = BUDGET_VERSION
            if row.usage_ledger is None:
                row.usage_ledger = {}
            session.flush()
            return self._snapshot(row)

    def prepare_run_resume(self, lease: JobLease) -> None:
        if lease.attempt <= 1:
            return
        with self._sessions.begin() as session:
            self._require_lease(session, lease.run_id, lease.token)
            row = session.get(RunRow, lease.run_id)
            if row is None:
                raise NotFoundError("run not found")
            current = RunStatus(row.status)
            if current.terminal or current is RunStatus.QUEUED:
                return
            previous = current.value
            row.status = RunStatus.PLANNING.value
            self._append_event(
                session,
                lease.run_id,
                "run.resumed",
                {
                    "attempt": lease.attempt,
                    "previous_status": previous,
                    "status": RunStatus.PLANNING.value,
                },
            )

    def authorize_run_execution(self, run_id: UUID, *, lease_token: UUID) -> None:
        with self._sessions() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            membership = session.scalar(
                select(WorkspaceMembershipRow.id).where(
                    WorkspaceMembershipRow.workspace_id == run.workspace_id,
                    WorkspaceMembershipRow.user_id == run.created_by_user_id,
                )
            )
            if membership is None:
                raise RunAuthorizationError("run creator no longer has workspace access")
            ids = [UUID(value) for value in (run.document_ids or [])]
            if ids:
                owned = set(
                    session.scalars(
                        select(UserDocumentRow.id).where(
                            UserDocumentRow.id.in_(ids),
                            UserDocumentRow.workspace_id == run.workspace_id,
                        )
                    ).all()
                )
                missing = [value for value in ids if value not in owned]
                if missing:
                    raise RunAuthorizationError(f"document access revoked or deleted: {missing[0]}")

    def get_documents_for_run(
        self, run_id: UUID, document_ids: list[UUID], *, lease_token: UUID
    ) -> list[UserDocumentRow]:
        if not document_ids:
            return []
        with self._sessions() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            admitted = {UUID(value) for value in (run.document_ids or [])}
            if not set(document_ids).issubset(admitted):
                raise RunAuthorizationError(
                    "run requested documents outside its admitted document set"
                )
            rows = session.scalars(
                select(UserDocumentRow).where(
                    UserDocumentRow.id.in_(document_ids),
                    UserDocumentRow.workspace_id == run.workspace_id,
                )
            ).all()
            by_id = {row.id: row for row in rows}
            missing = [value for value in document_ids if value not in by_id]
            if missing:
                raise RunAuthorizationError(f"document access revoked or deleted: {missing[0]}")
            return [by_id[value] for value in document_ids]

    def consume_run_usage(
        self, run_id: UUID, *, delta: dict[str, int], limits: dict[str, int], lease_token: UUID
    ) -> dict[str, int]:
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            row = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if row is None:
                raise NotFoundError("run not found")
            ledger = {str(k): int(v) for k, v in (row.usage_ledger or {}).items()}
            for key, amount in delta.items():
                if amount < 0:
                    raise ValueError("run usage deltas cannot be negative")
                candidate = ledger.get(key, 0) + int(amount)
                if key in limits and candidate > limits[key]:
                    raise RunBudgetExceededError(
                        f"run budget exhausted for {key}: {candidate} > {limits[key]}"
                    )
                ledger[key] = candidate
            row.usage_ledger = ledger
            session.flush()
            return dict(ledger)

    def list_runs_for_conversation(
        self, conversation_id: UUID, limit: int = 50
    ) -> list[RunSnapshot]:
        with self._sessions() as session:
            exists = self._conversation_row(session, conversation_id)
            if exists is None:
                raise NotFoundError("conversation not found")
            rows = session.scalars(
                select(RunRow)
                .where(
                    RunRow.conversation_id == conversation_id,
                    RunRow.workspace_id == exists.workspace_id,
                )
                .order_by(RunRow.created_at.desc())
                .limit(limit)
            ).all()
            return [self._snapshot(row) for row in rows]

    @staticmethod
    def _document_view(row: UserDocumentRow) -> DocumentView:
        return DocumentView(
            id=row.id,
            name=row.name,
            mime_type=row.mime_type,
            byte_count=row.byte_count,
            content_hash=row.content_hash,
            status=DocumentStatus(row.status),
            page_count=row.page_count,
            warnings=list(row.warnings or []),
            parser_version=row.parser_version,
            asset_id=row.asset_version_id,
            lexical_ready=bool(row.lexical_ready),
            semantic_ready=bool(row.semantic_ready),
            created_at=row.created_at,
        )

    @staticmethod
    def _asset_view(row: AssetVersionRow) -> AssetView:
        return AssetView(
            id=row.id,
            name=row.original_name,
            mime_type=row.mime_type,
            byte_count=row.byte_count,
            sha256=row.sha256,
            status=AssetStatus(row.status),
            width=row.width,
            height=row.height,
            page_count=row.page_count,
            duration_ms=row.duration_ms,
            cloud_media_allowed=bool(row.cloud_media_allowed),
            created_at=row.created_at,
        )

    @staticmethod
    def _ingestion_view(row: IngestionJobRow) -> IngestionView:
        return IngestionView(
            id=row.id,
            asset_id=row.asset_version_id,
            document_id=row.document_id,
            status=IngestionStatus(row.status),
            stage=IngestionStage(row.stage),
            lexical_ready=bool(row.lexical_ready),
            semantic_ready=bool(row.semantic_ready),
            cancellation_requested=bool(row.cancellation_requested),
            warnings=list(row.warnings or []),
            error_code=row.error_code,
            error_message=row.error_message,
            last_seq=int(row.last_seq or 0),
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
        )

    def _append_ingestion_event(
        self,
        session: Session,
        row: IngestionJobRow,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        row.last_seq = int(row.last_seq or 0) + 1
        row.updated_at = datetime.now(UTC)
        session.add(
            IngestionEventRow(
                workspace_id=row.workspace_id,
                ingestion_id=row.id,
                seq=row.last_seq,
                event_type=event_type,
                schema_version=1,
                payload=payload or {},
                created_at=row.updated_at,
            )
        )

    def create_asset_ingestion(
        self,
        *,
        name: str,
        mime_type: str,
        byte_count: int,
        sha256: str,
        blob_key: str,
        width: int | None = None,
        height: int | None = None,
        cloud_media_allowed: bool = False,
    ) -> tuple[AssetView, IngestionView]:
        principal = self._request_principal()
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            self._ensure_local_identity(session, principal)
            asset = AssetVersionRow(
                workspace_id=principal.workspace_id,
                created_by_user_id=principal.user_id,
                original_name=name,
                original_blob_key=blob_key,
                sha256=sha256,
                mime_type=mime_type,
                byte_count=byte_count,
                width=width,
                height=height,
                status=AssetStatus.QUEUED.value,
                cloud_media_allowed=cloud_media_allowed,
                media_metadata_json={},
                created_at=now,
            )
            session.add(asset)
            session.flush()
            ingestion = IngestionJobRow(
                workspace_id=principal.workspace_id,
                created_by_user_id=principal.user_id,
                asset_version_id=asset.id,
                status=IngestionStatus.QUEUED.value,
                stage=IngestionStage.QUEUED.value,
                created_at=now,
                updated_at=now,
            )
            session.add(ingestion)
            session.flush()
            self._append_ingestion_event(
                session,
                ingestion,
                "ingestion.queued",
                {"asset_id": str(asset.id), "mime_type": mime_type, "byte_count": byte_count},
            )
            session.flush()
            return self._asset_view(asset), self._ingestion_view(ingestion)

    def list_assets(self, limit: int = 100) -> list[AssetView]:
        with self._sessions() as session:
            stmt = select(AssetVersionRow)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(AssetVersionRow.workspace_id == workspace_id)
            rows = session.scalars(
                stmt.order_by(AssetVersionRow.created_at.desc()).limit(limit)
            ).all()
            return [self._asset_view(row) for row in rows]

    def get_asset_record(self, asset_id: UUID) -> AssetVersionRow:
        with self._sessions() as session:
            stmt = select(AssetVersionRow).where(AssetVersionRow.id == asset_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(AssetVersionRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("asset not found")
            session.expunge(row)
            return row

    def get_ingestion(self, ingestion_id: UUID) -> IngestionView:
        with self._sessions() as session:
            stmt = select(IngestionJobRow).where(IngestionJobRow.id == ingestion_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(IngestionJobRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("ingestion not found")
            return self._ingestion_view(row)

    def list_ingestions(self, limit: int = 100) -> list[IngestionView]:
        with self._sessions() as session:
            stmt = select(IngestionJobRow)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(IngestionJobRow.workspace_id == workspace_id)
            rows = session.scalars(
                stmt.order_by(IngestionJobRow.created_at.desc()).limit(limit)
            ).all()
            return [self._ingestion_view(row) for row in rows]

    def request_ingestion_cancel(self, ingestion_id: UUID) -> IngestionView:
        with self._sessions.begin() as session:
            stmt = (
                select(IngestionJobRow).where(IngestionJobRow.id == ingestion_id).with_for_update()
            )
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(IngestionJobRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("ingestion not found")
            status = IngestionStatus(row.status)
            if status.terminal:
                return self._ingestion_view(row)
            row.cancellation_requested = True
            if status is IngestionStatus.QUEUED:
                row.status = IngestionStatus.CANCELLED.value
                row.stage = IngestionStage.CANCELLED.value
                row.completed_at = datetime.now(UTC)
                asset = session.get(AssetVersionRow, row.asset_version_id)
                if asset is not None:
                    asset.status = AssetStatus.CANCELLED.value
                self._append_ingestion_event(session, row, "ingestion.cancelled", {"queued": True})
            else:
                self._append_ingestion_event(session, row, "ingestion.cancel.requested", {})
            session.flush()
            return self._ingestion_view(row)

    def retry_ingestion(self, ingestion_id: UUID) -> IngestionView:
        with self._sessions.begin() as session:
            stmt = (
                select(IngestionJobRow).where(IngestionJobRow.id == ingestion_id).with_for_update()
            )
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(IngestionJobRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("ingestion not found")
            if IngestionStatus(row.status) not in {
                IngestionStatus.FAILED,
                IngestionStatus.CANCELLED,
            }:
                raise ValueError("only failed or cancelled ingestions can be retried")
            row.status = IngestionStatus.QUEUED.value
            row.stage = IngestionStage.QUEUED.value
            row.cancellation_requested = False
            row.error_code = None
            row.error_message = None
            row.completed_at = None
            row.leased_until = None
            row.lease_token = None
            row.attempts = 0
            asset = session.get(AssetVersionRow, row.asset_version_id)
            if asset is not None:
                asset.status = AssetStatus.QUEUED.value
            self._append_ingestion_event(session, row, "ingestion.retried", {})
            session.flush()
            return self._ingestion_view(row)

    def list_ingestion_events(
        self, ingestion_id: UUID, after: int = 0, *, limit: int = 200
    ) -> list[IngestionEventEnvelope]:
        if after < 0:
            raise ValueError("event cursor cannot be negative")
        if not 1 <= limit <= 1000:
            raise ValueError("event page limit must be between 1 and 1000")
        with self._sessions() as session:
            stmt = select(IngestionJobRow).where(IngestionJobRow.id == ingestion_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(IngestionJobRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("ingestion not found")
            events = session.scalars(
                select(IngestionEventRow)
                .where(
                    IngestionEventRow.ingestion_id == ingestion_id, IngestionEventRow.seq > after
                )
                .order_by(IngestionEventRow.seq.asc())
                .limit(limit)
            ).all()
            return [
                IngestionEventEnvelope(
                    schema_version=event.schema_version,
                    ingestion_id=event.ingestion_id,
                    seq=event.seq,
                    event_type=event.event_type,
                    at=event.created_at,
                    payload=event.payload,
                )
                for event in events
            ]

    def claim_next_ingestion(
        self, *, lease_seconds: int = 60, max_attempts: int = 3
    ) -> IngestionLease | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = uuid4()
        with self._sessions.begin() as session:
            exhausted = session.scalars(
                select(IngestionJobRow)
                .where(
                    IngestionJobRow.attempts >= max_attempts,
                    or_(
                        IngestionJobRow.status == IngestionStatus.QUEUED.value,
                        (IngestionJobRow.status == IngestionStatus.RUNNING.value)
                        & (IngestionJobRow.leased_until < now),
                    ),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for job in exhausted:
                job.status = IngestionStatus.FAILED.value
                job.stage = IngestionStage.FAILED.value
                job.error_code = "INGESTION_RETRY_EXHAUSTED"
                job.error_message = (
                    f"ingestion retry budget exhausted after {job.attempts} attempts"
                )
                job.leased_until = None
                job.lease_token = None
                job.completed_at = now
                asset = session.get(AssetVersionRow, job.asset_version_id)
                if asset is not None:
                    asset.status = AssetStatus.FAILED.value
                self._append_ingestion_event(
                    session,
                    job,
                    "ingestion.failed",
                    {"code": job.error_code, "attempts": job.attempts},
                )

            row = session.scalar(
                select(IngestionJobRow)
                .where(
                    IngestionJobRow.cancellation_requested.is_(False),
                    or_(
                        IngestionJobRow.status == IngestionStatus.QUEUED.value,
                        (IngestionJobRow.status == IngestionStatus.RUNNING.value)
                        & (IngestionJobRow.leased_until < now),
                    ),
                    IngestionJobRow.attempts < max_attempts,
                )
                .order_by(IngestionJobRow.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            row.status = IngestionStatus.RUNNING.value
            row.stage = (
                IngestionStage.PARSING.value
                if row.document_id is None
                else IngestionStage.INDEXING.value
            )
            row.lease_token = token
            row.leased_until = expires
            row.attempts += 1
            asset = session.get(AssetVersionRow, row.asset_version_id)
            if asset is not None:
                asset.status = AssetStatus.PROCESSING.value
            self._append_ingestion_event(
                session,
                row,
                "ingestion.claimed",
                {"attempt": row.attempts, "lease_seconds": lease_seconds, "stage": row.stage},
            )
            return IngestionLease(
                ingestion_id=row.id,
                asset_id=row.asset_version_id,
                token=token,
                leased_until=expires,
                attempt=row.attempts,
            )

    def _require_ingestion_lease(
        self, session: Session, ingestion_id: UUID, token: UUID
    ) -> IngestionJobRow:
        row = session.scalar(select(IngestionJobRow).where(IngestionJobRow.id == ingestion_id))
        if row is None:
            raise NotFoundError("ingestion not found")
        if row.status != IngestionStatus.RUNNING.value or row.lease_token != token:
            raise StaleLeaseError("ingestion worker lease is stale")
        leased_until = row.leased_until
        if leased_until is None:
            raise StaleLeaseError("ingestion worker lease has expired")
        if leased_until.tzinfo is None:
            leased_until = leased_until.replace(tzinfo=UTC)
        if leased_until <= datetime.now(UTC):
            raise StaleLeaseError("ingestion worker lease has expired")
        return row

    def heartbeat_ingestion(
        self, lease: IngestionLease, *, lease_seconds: int = 60
    ) -> IngestionLease:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            row.leased_until = now + timedelta(seconds=lease_seconds)
            row.updated_at = now
            return IngestionLease(
                ingestion_id=lease.ingestion_id,
                asset_id=lease.asset_id,
                token=lease.token,
                leased_until=row.leased_until,
                attempt=row.attempts,
            )

    def authorize_ingestion_execution(self, lease: IngestionLease) -> None:
        with self._sessions() as session:
            row = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            membership = session.scalar(
                select(WorkspaceMembershipRow.id).where(
                    WorkspaceMembershipRow.workspace_id == row.workspace_id,
                    WorkspaceMembershipRow.user_id == row.created_by_user_id,
                )
            )
            if membership is None:
                raise RunAuthorizationError("ingestion creator no longer has workspace access")
            asset = session.get(AssetVersionRow, row.asset_version_id)
            if asset is None or asset.workspace_id != row.workspace_id:
                raise RunAuthorizationError(
                    "ingestion asset is missing or moved outside its workspace"
                )

    def get_ingestion_asset_for_worker(self, lease: IngestionLease) -> AssetVersionRow:
        with self._sessions() as session:
            row = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            asset = session.get(AssetVersionRow, row.asset_version_id)
            if asset is None or asset.workspace_id != row.workspace_id:
                raise RunAuthorizationError("ingestion asset is missing or unauthorized")
            session.expunge(asset)
            return asset

    def ingestion_cancel_requested(self, lease: IngestionLease) -> bool:
        with self._sessions() as session:
            row = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            return bool(row.cancellation_requested)

    def set_ingestion_asset_dimensions(
        self, lease: IngestionLease, *, width: int, height: int
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("asset dimensions must be positive")
        with self._sessions.begin() as session:
            job = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            asset = session.get(AssetVersionRow, job.asset_version_id)
            if asset is None or asset.workspace_id != job.workspace_id:
                raise RunAuthorizationError("ingestion asset is missing or unauthorized")
            asset.width = width
            asset.height = height

    def set_ingestion_asset_media_metadata(
        self,
        lease: IngestionLease,
        *,
        duration_ms: int,
        width: int | None,
        height: int | None,
        media_metadata: dict[str, object],
    ) -> None:
        if duration_ms < 0:
            raise ValueError("asset duration cannot be negative")
        with self._sessions.begin() as session:
            job = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            asset = session.get(AssetVersionRow, job.asset_version_id)
            if asset is None or asset.workspace_id != job.workspace_id:
                raise RunAuthorizationError("ingestion asset is missing or unauthorized")
            asset.duration_ms = duration_ms
            if width is not None:
                if width <= 0:
                    raise ValueError("asset width must be positive")
                asset.width = width
            if height is not None:
                if height <= 0:
                    raise ValueError("asset height must be positive")
                asset.height = height
            asset.media_metadata_json = dict(media_metadata)

    def set_ingestion_stage(
        self, lease: IngestionLease, stage: IngestionStage, *, warnings: list[str] | None = None
    ) -> None:
        with self._sessions.begin() as session:
            row = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            row.stage = stage.value
            if warnings is not None:
                row.warnings = list(dict.fromkeys([*(row.warnings or []), *warnings]))
            self._append_ingestion_event(
                session,
                row,
                "ingestion.stage",
                {"stage": stage.value, "warnings": list(row.warnings or [])},
            )

    def publish_ingestion_extraction(
        self,
        lease: IngestionLease,
        *,
        parser_id: str,
        parser_revision: str,
        model_revision: str | None,
        config_hash: str,
        output_hash: str,
        text_content: str,
        page_count: int | None,
        page_map: list[dict[str, int]],
        warnings: list[str],
        document_status: DocumentStatus,
        segments: list[ExtractionSegmentDraft],
        tables: list[ExtractionTableDraft],
        chunks: list[PreparedChunk],
    ) -> IngestionPublication:
        """Atomically publish one immutable extraction and the V1 compatibility document.

        The transaction boundary is the publication fence: a worker crash before commit publishes
        nothing; a retry after commit observes ``document_id`` and skips duplicate publication.
        """
        with self._sessions.begin() as session:
            job = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            if job.cancellation_requested:
                raise StaleLeaseError("ingestion was cancelled before publication")
            if job.document_id is not None:
                existing = session.get(UserDocumentRow, job.document_id)
                if existing is None:
                    raise RuntimeError("ingestion references a missing published document")
                extraction = session.scalar(
                    select(ExtractionVersionRow)
                    .where(
                        ExtractionVersionRow.asset_version_id == job.asset_version_id,
                        ExtractionVersionRow.config_hash == config_hash,
                    )
                    .order_by(ExtractionVersionRow.created_at.desc())
                )
                if extraction is None:
                    raise RuntimeError("ingestion publication is missing its extraction version")
                return IngestionPublication(existing.id, extraction.id)
            asset = session.get(AssetVersionRow, job.asset_version_id)
            if asset is None or asset.workspace_id != job.workspace_id:
                raise RunAuthorizationError("ingestion asset is missing or unauthorized")

            extraction = ExtractionVersionRow(
                workspace_id=job.workspace_id,
                asset_version_id=asset.id,
                parser_id=parser_id,
                parser_revision=parser_revision,
                model_revision=model_revision,
                config_hash=config_hash,
                status="ready" if document_status is DocumentStatus.READY else "partial",
                warnings=warnings,
                output_hash=output_hash,
                text=text_content,
                page_count=page_count,
                page_map=page_map,
                completed_at=datetime.now(UTC),
            )
            session.add(extraction)
            session.flush()

            document = UserDocumentRow(
                workspace_id=job.workspace_id,
                created_by_user_id=job.created_by_user_id,
                name=asset.original_name,
                mime_type=asset.mime_type,
                text=text_content,
                content_hash=asset.sha256,
                byte_count=asset.byte_count,
                blob_key=asset.original_blob_key,
                status=document_status.value,
                page_count=page_count,
                page_map=page_map,
                warnings=warnings,
                parser_version=f"{parser_id}:{parser_revision}",
                asset_version_id=asset.id,
                lexical_ready=bool(chunks),
                semantic_ready=False,
            )
            session.add(document)
            session.flush()

            segment_rows: list[EvidenceSegmentRow] = []
            table_segment_lookup: dict[tuple[str, int, int], UUID] = {}
            for draft in segments:
                digest_input = f"{draft.modality}\n{draft.text or ''}\n{json.dumps(draft.locator.model_dump(mode='json'), sort_keys=True)}"
                segment = EvidenceSegmentRow(
                    workspace_id=job.workspace_id,
                    extraction_version_id=extraction.id,
                    document_id=document.id,
                    modality=draft.modality,
                    text=draft.text,
                    locator_json=draft.locator.model_dump(mode="json"),
                    derivation_kind=draft.derivation_kind,
                    confidence=draft.confidence,
                    language=draft.language,
                    origin_group_id=draft.origin_group_id,
                    content_hash=hashlib.sha256(digest_input.encode("utf-8")).hexdigest(),
                )
                session.add(segment)
                session.flush()
                segment_rows.append(segment)
                if (
                    draft.table_key is not None
                    and draft.table_row is not None
                    and draft.table_column is not None
                ):
                    table_segment_lookup[(draft.table_key, draft.table_row, draft.table_column)] = (
                        segment.id
                    )

            for chunk in chunks:
                segment_id = None
                if chunk.segment_index is not None and 0 <= chunk.segment_index < len(segment_rows):
                    segment_id = segment_rows[chunk.segment_index].id
                session.add(
                    DocumentChunkRow(
                        document_id=document.id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        locator=chunk.locator,
                        evidence_segment_id=segment_id,
                    )
                )

            for table in tables:
                table_row = DocumentTableRow(
                    workspace_id=job.workspace_id,
                    extraction_version_id=extraction.id,
                    table_key=table.table_key,
                    page=table.page,
                    locator_json=table.locator.model_dump(mode="json") if table.locator else None,
                    rows=table.rows,
                    columns=table.columns,
                )
                session.add(table_row)
                session.flush()
                for cell in table.cells:
                    session.add(
                        DocumentTableCellRow(
                            workspace_id=job.workspace_id,
                            table_id=table_row.id,
                            segment_id=table_segment_lookup.get(
                                (table.table_key, cell.row, cell.column)
                            ),
                            row_index=cell.row,
                            column_index=cell.column,
                            row_span=cell.row_span,
                            column_span=cell.column_span,
                            raw_text=cell.raw_text,
                            normalized_value_json=cell.normalized_value,
                            unit=cell.unit,
                            is_header=cell.is_header,
                            locator_json=cell.locator.model_dump(mode="json")
                            if cell.locator
                            else None,
                        )
                    )

            job.document_id = document.id
            job.lexical_ready = bool(chunks)
            job.stage = IngestionStage.INDEXING.value
            job.warnings = list(dict.fromkeys([*(job.warnings or []), *warnings]))
            asset.page_count = page_count
            self._append_ingestion_event(
                session,
                job,
                "ingestion.lexical.ready",
                {
                    "document_id": str(document.id),
                    "extraction_version_id": str(extraction.id),
                    "segments": len(segment_rows),
                    "tables": len(tables),
                    "chunks": len(chunks),
                },
            )
            session.flush()
            return IngestionPublication(document.id, extraction.id)

    def publish_media_metadata(
        self,
        lease: IngestionLease,
        *,
        extraction_version_id: UUID,
        tracks: list[MediaTrackDraft],
        frames: list[tuple[MediaFrameDraft, str]],
        media_metadata: dict[str, object],
    ) -> None:
        """Publish derived media metadata under the same ingestion lease and workspace fence.

        Frame bytes are written to the BlobStore before this call. Their content-addressed
        keys can safely be retried; the DB rows are idempotent on immutable media identity.
        """
        with self._sessions.begin() as session:
            job = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            if job.cancellation_requested:
                raise StaleLeaseError("ingestion was cancelled before media publication")
            asset = session.get(AssetVersionRow, job.asset_version_id)
            extraction = session.get(ExtractionVersionRow, extraction_version_id)
            if (
                asset is None
                or asset.workspace_id != job.workspace_id
                or extraction is None
                or extraction.workspace_id != job.workspace_id
                or extraction.asset_version_id != asset.id
            ):
                raise RunAuthorizationError("media publication is missing or unauthorized")

            asset.media_metadata_json = dict(media_metadata)
            for draft in tracks:
                row = session.scalar(
                    select(MediaTrackRow).where(
                        MediaTrackRow.asset_version_id == asset.id,
                        MediaTrackRow.track_type == draft.track_type,
                        MediaTrackRow.stream_index == draft.stream_index,
                    )
                )
                if row is None:
                    row = MediaTrackRow(
                        workspace_id=job.workspace_id,
                        asset_version_id=asset.id,
                        extraction_version_id=extraction.id,
                        track_type=draft.track_type,
                        stream_index=draft.stream_index,
                    )
                    session.add(row)
                row.extraction_version_id = extraction.id
                row.codec_name = draft.codec_name
                row.language = draft.language
                row.duration_ms = draft.duration_ms
                row.sample_rate = draft.sample_rate
                row.channels = draft.channels
                row.width = draft.width
                row.height = draft.height
                row.average_frame_rate = draft.average_frame_rate
                row.metadata_json = dict(draft.metadata)

            published_frames = 0
            for draft, blob_key in frames:
                rendition = session.scalar(
                    select(AssetRenditionRow).where(
                        AssetRenditionRow.asset_version_id == asset.id,
                        AssetRenditionRow.kind == "video_frame",
                        AssetRenditionRow.content_hash == draft.content_hash,
                    )
                )
                if rendition is None:
                    rendition = AssetRenditionRow(
                        workspace_id=job.workspace_id,
                        asset_version_id=asset.id,
                        extraction_version_id=extraction.id,
                        kind="video_frame",
                        blob_key=blob_key,
                        mime_type="image/jpeg",
                        byte_count=len(draft.jpeg_bytes),
                        content_hash=draft.content_hash,
                    )
                    session.add(rendition)
                    session.flush()
                frame = session.scalar(
                    select(MediaFrameRow).where(
                        MediaFrameRow.asset_version_id == asset.id,
                        MediaFrameRow.presentation_time_ms == draft.presentation_time_ms,
                        MediaFrameRow.content_hash == draft.content_hash,
                    )
                )
                if frame is None:
                    frame = MediaFrameRow(
                        workspace_id=job.workspace_id,
                        asset_version_id=asset.id,
                        extraction_version_id=extraction.id,
                        rendition_id=rendition.id,
                        presentation_time_ms=draft.presentation_time_ms,
                        source_kind=draft.source_kind,
                        width=draft.width,
                        height=draft.height,
                        content_hash=draft.content_hash,
                        perceptual_hash=draft.perceptual_hash,
                    )
                    session.add(frame)
                    published_frames += 1

            self._append_ingestion_event(
                session,
                job,
                "media.ready",
                {
                    "asset_id": str(asset.id),
                    "tracks": len(tracks),
                    "frames": published_frames,
                    "duration_ms": asset.duration_ms,
                    "sampling_strategy": media_metadata.get("sampling_strategy"),
                },
            )

    def mark_document_semantic_ready(
        self, lease: IngestionLease, document_id: UUID, *, ready: bool
    ) -> None:
        with self._sessions.begin() as session:
            job = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            if job.document_id != document_id:
                raise RunAuthorizationError("document does not belong to ingestion")
            document = session.get(UserDocumentRow, document_id)
            if document is None or document.workspace_id != job.workspace_id:
                raise RunAuthorizationError("ingested document is missing or unauthorized")
            document.semantic_ready = ready
            job.semantic_ready = ready
            if ready:
                self._append_ingestion_event(
                    session, job, "index.ready", {"document_id": str(document_id)}
                )

    def complete_ingestion(
        self,
        lease: IngestionLease,
        *,
        partial: bool = False,
        warnings: list[str] | None = None,
    ) -> IngestionView:
        with self._sessions.begin() as session:
            job = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            if job.cancellation_requested:
                job.status = IngestionStatus.CANCELLED.value
                job.stage = IngestionStage.CANCELLED.value
                asset_status = AssetStatus.CANCELLED
                event_type = "ingestion.cancelled"
            else:
                job.status = (
                    IngestionStatus.PARTIAL.value if partial else IngestionStatus.READY.value
                )
                job.stage = IngestionStage.PARTIAL.value if partial else IngestionStage.READY.value
                asset_status = AssetStatus.PARTIAL if partial else AssetStatus.READY
                event_type = "ingestion.partial" if partial else "ingestion.ready"
            job.completed_at = datetime.now(UTC)
            job.leased_until = None
            job.lease_token = None
            if warnings:
                job.warnings = list(dict.fromkeys([*(job.warnings or []), *warnings]))
            asset = session.get(AssetVersionRow, job.asset_version_id)
            if asset is not None:
                asset.status = asset_status.value
            self._append_ingestion_event(
                session,
                job,
                event_type,
                {
                    "document_id": str(job.document_id) if job.document_id else None,
                    "lexical_ready": bool(job.lexical_ready),
                    "semantic_ready": bool(job.semantic_ready),
                    "warnings": list(job.warnings or []),
                },
            )
            session.flush()
            return self._ingestion_view(job)

    def fail_ingestion(
        self, lease: IngestionLease, *, code: str, message: str, warnings: list[str] | None = None
    ) -> IngestionView:
        with self._sessions.begin() as session:
            job = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            job.status = IngestionStatus.FAILED.value
            job.stage = IngestionStage.FAILED.value
            job.error_code = code[:80]
            job.error_message = message[:4000]
            job.completed_at = datetime.now(UTC)
            job.leased_until = None
            job.lease_token = None
            if warnings:
                job.warnings = list(dict.fromkeys([*(job.warnings or []), *warnings]))
            asset = session.get(AssetVersionRow, job.asset_version_id)
            if asset is not None:
                asset.status = AssetStatus.FAILED.value
            self._append_ingestion_event(
                session,
                job,
                "ingestion.failed",
                {"code": job.error_code, "message": job.error_message},
            )
            session.flush()
            return self._ingestion_view(job)

    def create_text_document(self, payload: DocumentTextCreate) -> DocumentView:
        # Compatibility entrypoint used by older callers. New API code routes through
        # DocumentIngestService so the blob and chunk indexes are created together.
        raw = payload.text.encode("utf-8")
        return self.create_user_document(
            name=payload.name.strip(),
            mime_type=payload.mime_type,
            text=payload.text,
            raw_bytes=raw,
            blob_key=None,
            status=DocumentStatus.READY,
            page_count=None,
            page_map=[],
            warnings=[],
            parser_version="plain-text-v1",
            chunks=[],
        )

    def create_user_document(
        self,
        *,
        name: str,
        mime_type: str,
        text: str,
        raw_bytes: bytes,
        blob_key: str | None,
        status: DocumentStatus,
        page_count: int | None,
        page_map: list[dict[str, int]],
        warnings: list[str],
        parser_version: str | None,
        chunks: list[PreparedChunk],
    ) -> DocumentView:
        digest = hashlib.sha256(raw_bytes).hexdigest()
        principal = self._request_principal()
        with self._sessions.begin() as session:
            self._ensure_local_identity(session, principal)
            row = UserDocumentRow(
                workspace_id=principal.workspace_id,
                created_by_user_id=principal.user_id,
                name=name,
                mime_type=mime_type,
                text=text,
                content_hash=digest,
                byte_count=len(raw_bytes),
                blob_key=blob_key,
                status=status.value,
                page_count=page_count,
                page_map=page_map,
                warnings=warnings,
                parser_version=parser_version,
            )
            session.add(row)
            session.flush()
            for chunk in chunks:
                session.add(
                    DocumentChunkRow(
                        document_id=row.id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        locator=chunk.locator,
                    )
                )
            session.flush()
            return self._document_view(row)

    def list_documents(self, limit: int = 100) -> list[DocumentView]:
        with self._sessions() as session:
            stmt = select(UserDocumentRow)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(UserDocumentRow.workspace_id == workspace_id)
            rows = session.scalars(
                stmt.order_by(UserDocumentRow.created_at.desc()).limit(limit)
            ).all()
            return [self._document_view(row) for row in rows]

    def get_documents(self, document_ids: list[UUID]) -> list[UserDocumentRow]:
        if not document_ids:
            return []
        with self._sessions() as session:
            stmt = select(UserDocumentRow).where(UserDocumentRow.id.in_(document_ids))
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(UserDocumentRow.workspace_id == workspace_id)
            rows = session.scalars(stmt).all()
            by_id = {row.id: row for row in rows}
            missing = [doc_id for doc_id in document_ids if doc_id not in by_id]
            if missing:
                raise NotFoundError(f"document not found: {missing[0]}")
            return [by_id[doc_id] for doc_id in document_ids]

    def get_text_documents(self, document_ids: list[UUID]) -> list[UserDocumentRow]:
        return self.get_documents(document_ids)

    def delete_asset_with_blobs(self, asset_id: UUID) -> list[str]:
        """Delete one authorized asset and all mutable derivatives.

        Finalized run evidence intentionally keeps its copied text/locator snapshot, but
        its live segment pointer is cleared before the segment is removed.  Explicit
        child cleanup keeps SQLite demo semantics aligned with PostgreSQL even when
        SQLite foreign-key cascades are disabled.
        """
        with self._sessions.begin() as session:
            stmt = select(AssetVersionRow).where(AssetVersionRow.id == asset_id).with_for_update()
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(AssetVersionRow.workspace_id == workspace_id)
            asset = session.scalar(stmt)
            if asset is None:
                raise NotFoundError("asset not found")

            candidate_keys: list[str] = [asset.original_blob_key]
            candidate_keys.extend(
                str(value)
                for value in session.scalars(
                    select(AssetRenditionRow.blob_key).where(
                        AssetRenditionRow.asset_version_id == asset_id
                    )
                ).all()
            )
            candidate_keys.extend(
                str(value)
                for value in session.scalars(
                    select(UserDocumentRow.blob_key).where(
                        UserDocumentRow.asset_version_id == asset_id,
                        UserDocumentRow.blob_key.is_not(None),
                    )
                ).all()
                if value
            )

            ingestion_ids = list(
                session.scalars(
                    select(IngestionJobRow.id).where(IngestionJobRow.asset_version_id == asset_id)
                ).all()
            )
            extraction_ids = list(
                session.scalars(
                    select(ExtractionVersionRow.id).where(
                        ExtractionVersionRow.asset_version_id == asset_id
                    )
                ).all()
            )
            segment_ids = (
                list(
                    session.scalars(
                        select(EvidenceSegmentRow.id).where(
                            EvidenceSegmentRow.extraction_version_id.in_(extraction_ids)
                        )
                    ).all()
                )
                if extraction_ids
                else []
            )
            table_ids = (
                list(
                    session.scalars(
                        select(DocumentTableRow.id).where(
                            DocumentTableRow.extraction_version_id.in_(extraction_ids)
                        )
                    ).all()
                )
                if extraction_ids
                else []
            )
            document_ids = list(
                session.scalars(
                    select(UserDocumentRow.id).where(UserDocumentRow.asset_version_id == asset_id)
                ).all()
            )
            chunk_ids = (
                list(
                    session.scalars(
                        select(DocumentChunkRow.id).where(
                            DocumentChunkRow.document_id.in_(document_ids)
                        )
                    ).all()
                )
                if document_ids
                else []
            )

            # Retained finalized run evidence is a historical snapshot, not a live
            # authorization to the deleted private segment. PostgreSQL would apply
            # ON DELETE SET NULL; do it explicitly for SQLite/demo parity.
            if segment_ids:
                session.execute(
                    update(EvidenceRow)
                    .where(EvidenceRow.segment_id.in_(segment_ids))
                    .values(segment_id=None)
                )
            if ingestion_ids:
                session.execute(
                    delete(IngestionEventRow).where(
                        IngestionEventRow.ingestion_id.in_(ingestion_ids)
                    )
                )
            if chunk_ids:
                session.execute(
                    delete(DocumentEmbeddingRow).where(DocumentEmbeddingRow.chunk_id.in_(chunk_ids))
                )
            if document_ids:
                session.execute(
                    delete(DocumentChunkRow).where(DocumentChunkRow.document_id.in_(document_ids))
                )
            if table_ids:
                session.execute(
                    delete(DocumentTableCellRow).where(DocumentTableCellRow.table_id.in_(table_ids))
                )
            session.execute(delete(MediaFrameRow).where(MediaFrameRow.asset_version_id == asset_id))
            session.execute(delete(MediaTrackRow).where(MediaTrackRow.asset_version_id == asset_id))
            session.execute(
                delete(AssetRenditionRow).where(AssetRenditionRow.asset_version_id == asset_id)
            )
            if table_ids:
                session.execute(delete(DocumentTableRow).where(DocumentTableRow.id.in_(table_ids)))
            if segment_ids:
                session.execute(
                    delete(EvidenceSegmentRow).where(EvidenceSegmentRow.id.in_(segment_ids))
                )
            if document_ids:
                session.execute(delete(UserDocumentRow).where(UserDocumentRow.id.in_(document_ids)))
            if extraction_ids:
                session.execute(
                    delete(ExtractionVersionRow).where(ExtractionVersionRow.id.in_(extraction_ids))
                )
            if ingestion_ids:
                session.execute(
                    delete(IngestionJobRow).where(IngestionJobRow.id.in_(ingestion_ids))
                )
            session.execute(delete(AssetVersionRow).where(AssetVersionRow.id == asset_id))
            session.flush()

            deletable: list[str] = []
            for blob_key in dict.fromkeys(candidate_keys):
                if not blob_key:
                    continue
                document_refs = int(
                    session.scalar(
                        select(func.count())
                        .select_from(UserDocumentRow)
                        .where(UserDocumentRow.blob_key == blob_key)
                    )
                    or 0
                )
                asset_refs = int(
                    session.scalar(
                        select(func.count())
                        .select_from(AssetVersionRow)
                        .where(AssetVersionRow.original_blob_key == blob_key)
                    )
                    or 0
                )
                rendition_refs = int(
                    session.scalar(
                        select(func.count())
                        .select_from(AssetRenditionRow)
                        .where(AssetRenditionRow.blob_key == blob_key)
                    )
                    or 0
                )
                if document_refs + asset_refs + rendition_refs == 0:
                    deletable.append(blob_key)
            return deletable

    def delete_document_with_blobs(self, document_id: UUID) -> list[str]:
        """Delete a compatibility document + owned asset and return now-unreferenced blob keys."""
        with self._sessions.begin() as session:
            stmt = select(UserDocumentRow).where(UserDocumentRow.id == document_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(UserDocumentRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("document not found")
            candidate_keys: list[str] = []
            asset_version_id = row.asset_version_id
            if row.blob_key:
                candidate_keys.append(row.blob_key)
            if asset_version_id is not None:
                rendition_stmt = select(AssetRenditionRow.blob_key).where(
                    AssetRenditionRow.asset_version_id == asset_version_id
                )
                if workspace_id is not None:
                    rendition_stmt = rendition_stmt.where(
                        AssetRenditionRow.workspace_id == workspace_id
                    )
                candidate_keys.extend(str(value) for value in session.scalars(rendition_stmt).all())
            session.delete(row)
            session.flush()
            if asset_version_id is not None:
                # Delete media metadata explicitly before the asset. PostgreSQL enforces
                # the ON DELETE cascades, but SQLite demo/test databases can run without
                # FK cascade enforcement depending on connection configuration. Explicit
                # cleanup keeps retention semantics identical across supported profiles and
                # ensures rendition blob-reference checks observe the post-delete state.
                session.execute(
                    delete(MediaFrameRow).where(MediaFrameRow.asset_version_id == asset_version_id)
                )
                session.execute(
                    delete(MediaTrackRow).where(MediaTrackRow.asset_version_id == asset_version_id)
                )
                session.execute(
                    delete(AssetRenditionRow).where(
                        AssetRenditionRow.asset_version_id == asset_version_id
                    )
                )
                session.flush()
                asset = session.get(AssetVersionRow, asset_version_id)
                if asset is not None:
                    if asset.original_blob_key:
                        candidate_keys.append(asset.original_blob_key)
                    session.delete(asset)
                    session.flush()

            deletable: list[str] = []
            for blob_key in dict.fromkeys(candidate_keys):
                document_refs = int(
                    session.scalar(
                        select(func.count())
                        .select_from(UserDocumentRow)
                        .where(UserDocumentRow.blob_key == blob_key)
                    )
                    or 0
                )
                asset_refs = int(
                    session.scalar(
                        select(func.count())
                        .select_from(AssetVersionRow)
                        .where(AssetVersionRow.original_blob_key == blob_key)
                    )
                    or 0
                )
                rendition_refs = int(
                    session.scalar(
                        select(func.count())
                        .select_from(AssetRenditionRow)
                        .where(AssetRenditionRow.blob_key == blob_key)
                    )
                    or 0
                )
                if document_refs + asset_refs + rendition_refs == 0:
                    deletable.append(blob_key)
            return deletable

    def delete_document(self, document_id: UUID) -> tuple[str | None, bool]:
        with self._sessions.begin() as session:
            stmt = select(UserDocumentRow).where(UserDocumentRow.id == document_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(UserDocumentRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("document not found")
            blob_key = row.blob_key
            asset_version_id = row.asset_version_id
            session.delete(row)
            session.flush()
            if asset_version_id is not None:
                asset = session.get(AssetVersionRow, asset_version_id)
                if asset is not None:
                    session.delete(asset)
                    session.flush()
            still_referenced = False
            if blob_key:
                still_referenced = bool(
                    session.scalar(
                        select(func.count())
                        .select_from(UserDocumentRow)
                        .where(UserDocumentRow.blob_key == blob_key)
                    )
                ) or bool(
                    session.scalar(
                        select(func.count())
                        .select_from(AssetVersionRow)
                        .where(AssetVersionRow.original_blob_key == blob_key)
                    )
                )
            return blob_key, still_referenced

    def get_document_chunks(self, document_ids: list[UUID]) -> list[DocumentChunkRow]:
        if not document_ids:
            return []
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(DocumentChunkRow)
                    .where(DocumentChunkRow.document_id.in_(document_ids))
                    .order_by(DocumentChunkRow.document_id, DocumentChunkRow.chunk_index)
                ).all()
            )

    def get_document_chunks_by_ids(self, chunk_ids: list[UUID]) -> list[DocumentChunkRow]:
        if not chunk_ids:
            return []
        with self._sessions() as session:
            rows = session.scalars(
                select(DocumentChunkRow).where(DocumentChunkRow.id.in_(chunk_ids))
            ).all()
            by_id = {row.id: row for row in rows}
            return [by_id[value] for value in chunk_ids if value in by_id]

    def lexical_search_document_chunks(
        self, document_ids: list[UUID], *, query: str, limit: int = 30
    ) -> list[tuple[DocumentChunkRow, float]]:
        """Return bounded lexical candidates without loading the full corpus on PostgreSQL."""
        if not document_ids or not query.strip():
            return []
        engine = self._sessions.kw.get("bind")
        dialect = engine.dialect.name if engine is not None else "unknown"
        with self._sessions() as session:
            if dialect == "postgresql":
                placeholders = ",".join(f":doc_{index}" for index in range(len(document_ids)))
                params: dict[str, object] = {"query": query, "limit": limit}
                params.update({f"doc_{index}": value for index, value in enumerate(document_ids)})
                rows = session.execute(
                    text(
                        f"""
                        SELECT c.id,
                               ts_rank_cd(
                                   to_tsvector('simple', coalesce(c.text, '')),
                                   websearch_to_tsquery('simple', :query)
                               ) AS score
                        FROM document_chunks c
                        WHERE c.document_id IN ({placeholders})
                          AND to_tsvector('simple', coalesce(c.text, '')) @@ websearch_to_tsquery('simple', :query)
                        ORDER BY score DESC, c.id
                        LIMIT :limit
                        """
                    ),
                    params,
                ).all()
                if not rows:
                    return []
                ids = [UUID(str(row[0])) for row in rows]
                by_id = {
                    item.id: item
                    for item in session.scalars(
                        select(DocumentChunkRow).where(DocumentChunkRow.id.in_(ids))
                    ).all()
                }
                return [
                    (by_id[chunk_id], float(score))
                    for chunk_id, score in ((UUID(str(r[0])), r[1]) for r in rows)
                    if chunk_id in by_id
                ]

            # SQLite remains the deterministic demo/test fallback. It intentionally has no
            # performance claim; production retrieval uses the indexed PostgreSQL path above.
            candidates = session.scalars(
                select(DocumentChunkRow).where(DocumentChunkRow.document_id.in_(document_ids))
            ).all()
            terms = [part.casefold() for part in query.replace("-", " ").split() if len(part) > 1]
            scored: list[tuple[DocumentChunkRow, float]] = []
            for row in candidates:
                lower = row.text.casefold()
                score = float(sum(lower.count(term) for term in terms))
                phrase = " ".join(terms[:8])
                if phrase and phrase in lower:
                    score += 2.0
                if score > 0:
                    scored.append((row, score))
            scored.sort(key=lambda item: (-item[1], item[0].chunk_index))
            return scored[:limit]

    def get_rendition_record(self, rendition_id: UUID) -> AssetRenditionRow:
        with self._sessions() as session:
            stmt = select(AssetRenditionRow).where(AssetRenditionRow.id == rendition_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(AssetRenditionRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("rendition not found")
            session.expunge(row)
            return row

    def get_media_storyboard(self, asset_id: UUID) -> MediaStoryboardView:
        with self._sessions() as session:
            stmt = select(AssetVersionRow).where(AssetVersionRow.id == asset_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(AssetVersionRow.workspace_id == workspace_id)
            asset = session.scalar(stmt)
            if asset is None:
                raise NotFoundError("asset not found")

            track_stmt = (
                select(MediaTrackRow)
                .where(MediaTrackRow.asset_version_id == asset_id)
                .order_by(MediaTrackRow.stream_index.asc(), MediaTrackRow.created_at.asc())
            )
            frame_stmt = (
                select(MediaFrameRow)
                .where(MediaFrameRow.asset_version_id == asset_id)
                .order_by(MediaFrameRow.presentation_time_ms.asc(), MediaFrameRow.created_at.asc())
            )
            if workspace_id is not None:
                track_stmt = track_stmt.where(MediaTrackRow.workspace_id == workspace_id)
                frame_stmt = frame_stmt.where(MediaFrameRow.workspace_id == workspace_id)
            tracks = session.scalars(track_stmt).all()
            frames = session.scalars(frame_stmt).all()
            metadata = dict(asset.media_metadata_json or {})
            sampled = metadata.get("sampled_times_ms")
            sampled_times = [int(value) for value in sampled] if isinstance(sampled, list) else []
            warning = metadata.get("visual_coverage_warning")
            strategy = metadata.get("sampling_strategy")
            waveform = metadata.get("waveform_peaks")
            waveform_peaks = (
                [max(0.0, min(1.0, float(value))) for value in waveform[:120]]
                if isinstance(waveform, list)
                else []
            )
            return MediaStoryboardView(
                asset_id=asset.id,
                duration_ms=asset.duration_ms,
                sampling_strategy=str(strategy or "transcript-only"),
                sampled_times_ms=sampled_times,
                waveform_peaks=waveform_peaks,
                visual_coverage_warning=str(warning) if warning else None,
                tracks=[
                    MediaTrackView(
                        id=row.id,
                        asset_id=row.asset_version_id,
                        extraction_version_id=row.extraction_version_id,
                        track_type=row.track_type,
                        stream_index=row.stream_index,
                        codec_name=row.codec_name,
                        language=row.language,
                        duration_ms=row.duration_ms,
                        sample_rate=row.sample_rate,
                        channels=row.channels,
                        width=row.width,
                        height=row.height,
                        average_frame_rate=row.average_frame_rate,
                        metadata=dict(row.metadata_json or {}),
                        created_at=row.created_at,
                    )
                    for row in tracks
                ],
                frames=[
                    MediaFrameView(
                        id=row.id,
                        asset_id=row.asset_version_id,
                        extraction_version_id=row.extraction_version_id,
                        rendition_id=row.rendition_id,
                        presentation_time_ms=row.presentation_time_ms,
                        source_kind=row.source_kind,
                        width=row.width,
                        height=row.height,
                        content_hash=row.content_hash,
                        content_url=f"/api/v2/renditions/{row.rendition_id}/content",
                        created_at=row.created_at,
                    )
                    for row in frames
                ],
            )

    def get_segment(self, segment_id: UUID) -> SegmentView:
        from pydantic import TypeAdapter

        locator_adapter = TypeAdapter(EvidenceLocator)
        with self._sessions() as session:
            stmt = (
                select(EvidenceSegmentRow, ExtractionVersionRow.asset_version_id)
                .join(
                    ExtractionVersionRow,
                    ExtractionVersionRow.id == EvidenceSegmentRow.extraction_version_id,
                )
                .where(EvidenceSegmentRow.id == segment_id)
            )
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(EvidenceSegmentRow.workspace_id == workspace_id)
            result = session.execute(stmt).first()
            if result is None:
                raise NotFoundError("segment not found")
            row, asset_id = result
            return SegmentView(
                id=row.id,
                asset_id=asset_id,
                extraction_version_id=row.extraction_version_id,
                document_id=row.document_id,
                modality=row.modality,
                text=row.text,
                locator=locator_adapter.validate_python(row.locator_json),
                derivation_kind=row.derivation_kind,
                confidence=row.confidence,
                language=row.language,
                content_hash=row.content_hash,
                origin_group_id=row.origin_group_id,
                created_at=row.created_at,
            )

    def get_table_for_segment(self, segment_id: UUID) -> TableView:
        from pydantic import TypeAdapter

        locator_adapter = TypeAdapter(EvidenceLocator)
        with self._sessions() as session:
            stmt = select(EvidenceSegmentRow).where(EvidenceSegmentRow.id == segment_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(EvidenceSegmentRow.workspace_id == workspace_id)
            segment = session.scalar(stmt)
            if segment is None:
                raise NotFoundError("segment not found")
            locator = locator_adapter.validate_python(segment.locator_json)
            if locator.kind != "table_cells":
                raise NotFoundError("segment does not belong to a table")
            table = session.scalar(
                select(DocumentTableRow).where(
                    DocumentTableRow.extraction_version_id == segment.extraction_version_id,
                    DocumentTableRow.table_key == locator.table_id,
                )
            )
            if table is None:
                raise NotFoundError("table not found")
            table_id = table.id
        return self.get_table(table_id)

    def get_table(self, table_id: UUID) -> TableView:
        from pydantic import TypeAdapter

        locator_adapter = TypeAdapter(EvidenceLocator)
        with self._sessions() as session:
            stmt = select(DocumentTableRow).where(DocumentTableRow.id == table_id)
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(DocumentTableRow.workspace_id == workspace_id)
            table_row = session.scalar(stmt)
            if table_row is None:
                raise NotFoundError("table not found")
            cells = session.scalars(
                select(DocumentTableCellRow)
                .where(DocumentTableCellRow.table_id == table_id)
                .order_by(DocumentTableCellRow.row_index, DocumentTableCellRow.column_index)
            ).all()
            return TableView(
                id=table_row.id,
                extraction_version_id=table_row.extraction_version_id,
                table_key=table_row.table_key,
                page=table_row.page,
                locator=locator_adapter.validate_python(table_row.locator_json)
                if table_row.locator_json
                else None,
                rows=table_row.rows,
                columns=table_row.columns,
                cells=[
                    TableCellView(
                        row=cell.row_index,
                        column=cell.column_index,
                        row_span=cell.row_span,
                        column_span=cell.column_span,
                        raw_text=cell.raw_text,
                        normalized_value=cell.normalized_value_json,
                        unit=cell.unit,
                        is_header=cell.is_header,
                        segment_id=cell.segment_id,
                    )
                    for cell in cells
                ],
            )

    def get_missing_embedding_chunks(
        self, document_ids: list[UUID], *, model_id: str, dimensions: int, limit: int = 500
    ) -> list[DocumentChunkRow]:
        if not document_ids:
            return []
        with self._sessions() as session:
            embedded = select(DocumentEmbeddingRow.chunk_id).where(
                DocumentEmbeddingRow.model_id == model_id,
                DocumentEmbeddingRow.dimensions == dimensions,
            )
            return list(
                session.scalars(
                    select(DocumentChunkRow)
                    .where(
                        DocumentChunkRow.document_id.in_(document_ids),
                        DocumentChunkRow.id.not_in(embedded),
                    )
                    .order_by(DocumentChunkRow.document_id, DocumentChunkRow.chunk_index)
                    .limit(limit)
                ).all()
            )

    def store_chunk_embeddings(
        self, *, model_id: str, dimensions: int, embeddings: list[tuple[UUID, list[float]]]
    ) -> None:
        if not embeddings:
            return
        engine = self._sessions.kw.get("bind")
        dialect = engine.dialect.name if engine is not None else "unknown"
        with self._sessions.begin() as session:
            for chunk_id, vector in embeddings:
                if len(vector) != dimensions:
                    raise ValueError("embedding dimension does not match configured index identity")
                existing = session.scalar(
                    select(DocumentEmbeddingRow).where(
                        DocumentEmbeddingRow.chunk_id == chunk_id,
                        DocumentEmbeddingRow.model_id == model_id,
                        DocumentEmbeddingRow.dimensions == dimensions,
                    )
                )
                if existing is None:
                    session.add(
                        DocumentEmbeddingRow(
                            chunk_id=chunk_id,
                            model_id=model_id,
                            dimensions=dimensions,
                            vector_json=vector,
                        )
                    )
                else:
                    existing.vector_json = vector
                if dialect == "postgresql":
                    literal = "[" + ",".join(f"{value:.10g}" for value in vector) + "]"
                    session.execute(
                        text(
                            """
                            INSERT INTO document_embeddings_pg (chunk_id, model_id, dimensions, embedding)
                            VALUES (:chunk_id, :model_id, :dimensions, CAST(:embedding AS vector))
                            ON CONFLICT (chunk_id, model_id, dimensions)
                            DO UPDATE SET embedding = EXCLUDED.embedding
                            """
                        ),
                        {
                            "chunk_id": chunk_id,
                            "model_id": model_id,
                            "dimensions": dimensions,
                            "embedding": literal,
                        },
                    )

    def vector_search_document_chunks(
        self,
        document_ids: list[UUID],
        *,
        model_id: str,
        dimensions: int,
        query_vector: list[float],
        limit: int = 30,
    ) -> list[tuple[UUID, float]]:
        if not document_ids or not query_vector:
            return []
        if len(query_vector) != dimensions:
            raise ValueError("query embedding dimension does not match configured index identity")
        engine = self._sessions.kw.get("bind")
        dialect = engine.dialect.name if engine is not None else "unknown"
        with self._sessions() as session:
            if dialect == "postgresql":
                placeholders = ",".join(f":doc_{index}" for index in range(len(document_ids)))
                literal = "[" + ",".join(f"{value:.10g}" for value in query_vector) + "]"
                params: dict[str, object] = {
                    "model_id": model_id,
                    "dimensions": dimensions,
                    "embedding": literal,
                    "limit": limit,
                }
                params.update({f"doc_{index}": doc_id for index, doc_id in enumerate(document_ids)})
                rows = session.execute(
                    text(
                        f"""
                        SELECT p.chunk_id, 1 - (p.embedding <=> CAST(:embedding AS vector)) AS score
                        FROM document_embeddings_pg p
                        JOIN document_chunks c ON c.id = p.chunk_id
                        WHERE c.document_id IN ({placeholders})
                          AND p.model_id = :model_id
                          AND p.dimensions = :dimensions
                        ORDER BY p.embedding <=> CAST(:embedding AS vector)
                        LIMIT :limit
                        """
                    ),
                    params,
                ).all()
                return [(UUID(str(row[0])), float(row[1])) for row in rows]

            rows = session.execute(
                select(DocumentEmbeddingRow.chunk_id, DocumentEmbeddingRow.vector_json)
                .join(DocumentChunkRow, DocumentChunkRow.id == DocumentEmbeddingRow.chunk_id)
                .where(
                    DocumentChunkRow.document_id.in_(document_ids),
                    DocumentEmbeddingRow.model_id == model_id,
                    DocumentEmbeddingRow.dimensions == dimensions,
                )
            ).all()
            import math

            def cosine(vector: list[float]) -> float:
                dot = sum(a * b for a, b in zip(query_vector, vector, strict=True))
                left = math.sqrt(sum(value * value for value in query_vector))
                right = math.sqrt(sum(value * value for value in vector))
                return dot / (left * right) if left and right else 0.0

            scored = [(chunk_id, cosine(list(vector))) for chunk_id, vector in rows]
            scored.sort(key=lambda item: item[1], reverse=True)
            return scored[:limit]

    def list_run_evidence(self, run_id: UUID) -> list[EvidenceView]:
        with self._sessions() as session:
            if self._run_row(session, run_id) is None:
                raise NotFoundError("run not found")
            ids = session.scalars(
                select(EvidenceRow.id)
                .where(EvidenceRow.run_id == run_id)
                .order_by(EvidenceRow.captured_at, EvidenceRow.id)
            ).all()
        return [self.get_evidence(evidence_id) for evidence_id in ids]

    def create_artifact(
        self,
        *,
        run_id: UUID,
        format: str,
        file_name: str,
        content_type: str,
        blob_key: str,
        byte_count: int,
        content_hash: str,
    ) -> ArtifactView:
        with self._sessions.begin() as session:
            if self._run_row(session, run_id) is None:
                raise NotFoundError("run not found")
            row = ArtifactRow(
                run_id=run_id,
                format=format,
                file_name=file_name,
                content_type=content_type,
                blob_key=blob_key,
                byte_count=byte_count,
                content_hash=content_hash,
            )
            session.add(row)
            session.flush()
            return ArtifactView(
                id=row.id,
                run_id=row.run_id,
                format=row.format,
                file_name=row.file_name,
                content_type=row.content_type,
                byte_count=row.byte_count,
                content_hash=row.content_hash,
                download_url=f"/api/v1/artifacts/{row.id}",
                created_at=row.created_at,
            )

    def get_artifact_record(self, artifact_id: UUID) -> ArtifactRow:
        with self._sessions() as session:
            stmt = (
                select(ArtifactRow)
                .join(RunRow, RunRow.id == ArtifactRow.run_id)
                .where(ArtifactRow.id == artifact_id)
            )
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(RunRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("artifact not found")
            session.expunge(row)
            return row

    def is_blob_referenced(self, blob_key: str) -> bool:
        with self._sessions() as session:
            return (
                bool(
                    session.scalar(
                        select(func.count())
                        .select_from(UserDocumentRow)
                        .where(UserDocumentRow.blob_key == blob_key)
                    )
                )
                or bool(
                    session.scalar(
                        select(func.count())
                        .select_from(ArtifactRow)
                        .where(ArtifactRow.blob_key == blob_key)
                    )
                )
                or bool(
                    session.scalar(
                        select(func.count())
                        .select_from(AssetVersionRow)
                        .where(AssetVersionRow.original_blob_key == blob_key)
                    )
                )
                or bool(
                    session.scalar(
                        select(func.count())
                        .select_from(AssetRenditionRow)
                        .where(AssetRenditionRow.blob_key == blob_key)
                    )
                )
            )

    def request_cancel(self, run_id: UUID) -> RunSnapshot:
        with self._sessions.begin() as session:
            row = self._run_row(session, run_id)
            if row is None:
                raise NotFoundError("run not found")
            if RunStatus(row.status).terminal:
                return self._snapshot(row)
            if not row.cancellation_requested:
                row.cancellation_requested = True
                self._append_event(session, row.id, "run.cancel.requested", {})
            session.flush()
            return self._snapshot(row)

    def claim_next_job(self, *, lease_seconds: int = 30, max_attempts: int = 3) -> JobLease | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = uuid4()
        with self._sessions.begin() as session:
            exhausted = session.scalars(
                select(JobRow)
                .where(
                    JobRow.attempts >= max_attempts,
                    or_(
                        JobRow.state == "queued",
                        (JobRow.state == "running") & (JobRow.leased_until < now),
                    ),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for job in exhausted:
                job.state = "failed"
                job.leased_until = None
                job.lease_token = None
                run = session.get(RunRow, job.run_id)
                if run is not None and not RunStatus(run.status).terminal:
                    run.status = RunStatus.FAILED.value
                    run.error_code = "WORKER_RETRY_EXHAUSTED"
                    run.error_message = (
                        f"worker retry budget exhausted after {job.attempts} attempts"
                    )
                    self._append_event(
                        session,
                        run.id,
                        "run.failed",
                        {"code": "WORKER_RETRY_EXHAUSTED", "attempts": job.attempts},
                    )

            stmt = (
                select(JobRow)
                .where(
                    JobRow.available_at <= now,
                    or_(
                        JobRow.state == "queued",
                        (JobRow.state == "running") & (JobRow.leased_until < now),
                    ),
                    JobRow.attempts < max_attempts,
                )
                .order_by(JobRow.priority.asc(), JobRow.available_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = session.scalar(stmt)
            if row is None:
                return None
            row.state = "running"
            row.lease_token = token
            row.leased_until = expires
            row.attempts += 1
            self._append_event(
                session,
                row.run_id,
                "job.claimed",
                {"attempt": row.attempts, "lease_seconds": lease_seconds},
            )
            return JobLease(
                run_id=row.run_id, token=token, leased_until=expires, attempt=row.attempts
            )

    def heartbeat(self, lease: JobLease, *, lease_seconds: int = 30) -> JobLease:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = self._require_lease(session, lease.run_id, lease.token)
            row.leased_until = now + timedelta(seconds=lease_seconds)
            return JobLease(
                run_id=lease.run_id,
                token=lease.token,
                leased_until=row.leased_until,
                attempt=row.attempts,
            )

    def record_event(
        self,
        run_id: UUID,
        event_type: str,
        payload: dict[str, object],
        *,
        lease_token: UUID | None = None,
    ) -> None:
        # Discovery tracks can emit events concurrently. The process-local lock makes the
        # SQLite demo path deterministic (SQLite ignores SELECT ... FOR UPDATE) while
        # PostgreSQL still provides the cross-process row lock in _append_event.
        with self._event_lock:
            with self._sessions.begin() as session:
                if lease_token is not None:
                    self._require_lease(session, run_id, lease_token)
                if self._run_row(session, run_id) is None:
                    raise NotFoundError("run not found")
                self._append_event(session, run_id, event_type, payload)

    def set_status(
        self,
        run_id: UUID,
        target: RunStatus,
        *,
        lease_token: UUID | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            if lease_token is not None:
                self._require_lease(session, run_id, lease_token)
            row = self._run_row(session, run_id)
            if row is None:
                raise NotFoundError("run not found")
            current = RunStatus(row.status)
            if current == target:
                return
            assert_transition(current, target)
            row.status = target.value
            event_type = "run.status"
            if target is RunStatus.COMPLETED:
                event_type = "run.completed"
            elif target is RunStatus.CANCELLED:
                event_type = "run.cancelled"
            elif target is RunStatus.PARTIAL:
                event_type = "run.partial"
            elif target is RunStatus.FAILED:
                event_type = "run.failed"
            self._append_event(
                session, run_id, event_type, {"status": target.value, **(payload or {})}
            )

    def is_cancel_requested(self, run_id: UUID, *, lease_token: UUID | None = None) -> bool:
        with self._sessions() as session:
            if lease_token is not None:
                self._require_lease(session, run_id, lease_token)
            value = session.scalar(select(RunRow.cancellation_requested).where(RunRow.id == run_id))
            if value is None:
                raise NotFoundError("run not found")
            return bool(value)

    def fail_run(
        self, run_id: UUID, code: str, message: str, *, lease_token: UUID | None = None
    ) -> None:
        with self._sessions.begin() as session:
            if lease_token is not None:
                self._require_lease(session, run_id, lease_token)
            row = self._run_row(session, run_id)
            if row is None:
                raise NotFoundError("run not found")
            if RunStatus(row.status).terminal:
                return
            row.error_code = code
            row.error_message = message[:2000]
            row.status = RunStatus.FAILED.value
            self._append_event(
                session, run_id, "run.failed", {"code": code, "message": message[:500]}
            )

    def add_source_and_evidence(
        self,
        run_id: UUID,
        *,
        title: str,
        url: str,
        domain: str,
        fetched_at: datetime,
        extraction_method: str,
        content_hash: str,
        passage: str,
        locator: str,
        support_status: SupportStatus = SupportStatus.SUPPORTED,
        lease_token: UUID | None = None,
    ) -> UUID:
        with self._sessions.begin() as session:
            if lease_token is not None:
                self._require_lease(session, run_id, lease_token)
            source = SourceRow(
                run_id=run_id,
                title=title,
                url=url,
                domain=domain,
                fetched_at=fetched_at,
                extraction_method=extraction_method,
                content_hash=content_hash,
            )
            session.add(source)
            session.flush()
            evidence = EvidenceRow(
                run_id=run_id,
                source_id=source.id,
                text=passage,
                locator=locator,
                support_status=support_status.value,
                captured_at=datetime.now(UTC),
            )
            session.add(evidence)
            session.flush()
            self._append_event(
                session,
                run_id,
                "evidence.added",
                {"evidence_id": str(evidence.id), "source_id": str(source.id), "title": title},
            )
            return evidence.id

    def persist_document_evidence(
        self,
        run_id: UUID,
        *,
        document: FetchedDocument,
        candidates: list[EvidenceCandidate],
        provider: str = "web",
        discovery_rank: int | None = None,
        snippet: str = "",
        lease_token: UUID | None = None,
    ) -> list[EvidencePacket]:
        """Persist immutable fetched evidence idempotently for retry/recovery."""
        from urllib.parse import urlparse

        with self._sessions.begin() as session:
            if lease_token is not None:
                self._require_lease(session, run_id, lease_token)
            source = None
            if document.canonical_identifier:
                source = session.scalar(
                    select(SourceRow).where(
                        SourceRow.run_id == run_id,
                        SourceRow.canonical_identifier == document.canonical_identifier,
                    )
                )
            if source is None:
                source = session.scalar(
                    select(SourceRow).where(
                        SourceRow.run_id == run_id,
                        SourceRow.content_hash == document.content_hash,
                        SourceRow.url == str(document.final_url),
                    )
                )
            new_source = source is None
            if source is None:
                source = SourceRow(
                    id=document.source_id,
                    run_id=run_id,
                    title=document.title,
                    url=str(document.final_url),
                    domain=urlparse(str(document.final_url)).netloc,
                    provider=provider,
                    source_kind=document.source_kind,
                    canonical_identifier=document.canonical_identifier,
                    published_at=document.published_at,
                    discovery_rank=discovery_rank,
                    snippet=snippet[:4000],
                    fetched_at=document.fetched_at,
                    extraction_method=document.extraction_method,
                    content_hash=document.content_hash,
                    origin_group_id=source_origin_group(document),
                )
                session.add(source)
                session.flush()
            if source.origin_group_id is None:
                source.origin_group_id = source_origin_group(document)
            version = session.scalar(
                select(DocumentVersionRow).where(
                    DocumentVersionRow.source_id == source.id,
                    DocumentVersionRow.content_hash == document.content_hash,
                    DocumentVersionRow.final_url == str(document.final_url),
                )
            )
            new_version = version is None
            if version is None:
                version = DocumentVersionRow(
                    source_id=source.id,
                    requested_url=str(document.url),
                    final_url=str(document.final_url),
                    content_hash=document.content_hash,
                    extraction_method=document.extraction_method,
                    mime_type=document.mime_type,
                    byte_count=document.byte_count,
                    text=document.text,
                    page_map=document.page_map,
                    fetched_at=document.fetched_at,
                )
                session.add(version)
                session.flush()
            if new_source or new_version:
                self._append_event(
                    session,
                    run_id,
                    "source.read",
                    {
                        "source_id": str(source.id),
                        "document_version_id": str(version.id),
                        "title": source.title,
                        "url": source.url,
                        "content_hash": version.content_hash,
                    },
                )
            packets: list[EvidencePacket] = []
            for candidate in candidates:
                if candidate.source_id != document.source_id:
                    raise ValueError("evidence candidate does not belong to fetched document")
                if (
                    candidate.char_end > len(document.text)
                    or candidate.char_start >= candidate.char_end
                ):
                    raise ValueError("evidence candidate has invalid source offsets")
                if (
                    document.text[candidate.char_start : candidate.char_end].strip()
                    != candidate.text.strip()
                ):
                    raise ValueError("evidence text does not match immutable document version")
                evidence = session.scalar(
                    select(EvidenceRow).where(
                        EvidenceRow.run_id == run_id,
                        EvidenceRow.document_version_id == version.id,
                        EvidenceRow.char_start == candidate.char_start,
                        EvidenceRow.char_end == candidate.char_end,
                        EvidenceRow.locator == candidate.locator,
                    )
                )
                if evidence is None:
                    evidence = EvidenceRow(
                        run_id=run_id,
                        source_id=source.id,
                        document_version_id=version.id,
                        text=candidate.text,
                        locator=candidate.locator,
                        char_start=candidate.char_start,
                        char_end=candidate.char_end,
                        page_start=candidate.page_start,
                        page_end=candidate.page_end,
                        segment_id=candidate.segment_id,
                        support_status=SupportStatus.SUPPORTED.value,
                        captured_at=datetime.now(UTC),
                    )
                    session.add(evidence)
                    session.flush()
                    self._append_event(
                        session,
                        run_id,
                        "evidence.added",
                        {
                            "evidence_id": str(evidence.id),
                            "source_id": str(source.id),
                            "document_version_id": str(version.id),
                            "locator": candidate.locator,
                            "page_start": candidate.page_start,
                            "page_end": candidate.page_end,
                            "segment_id": str(candidate.segment_id)
                            if candidate.segment_id
                            else None,
                        },
                    )
                elif evidence.segment_id is None and candidate.segment_id is not None:
                    evidence.segment_id = candidate.segment_id
                packets.append(
                    EvidencePacket(
                        evidence_id=evidence.id,
                        source_id=source.id,
                        origin_group_id=source.origin_group_id,
                        title=source.title,
                        url=source.url,
                        domain=source.domain,
                        text=evidence.text,
                        locator=evidence.locator,
                        captured_at=evidence.captured_at,
                        content_hash=version.content_hash,
                    )
                )
            return packets

    def finalize_answer(
        self,
        run_id: UUID,
        markdown: str,
        claims: list[
            FinalizedClaim | tuple[str, list[UUID]] | tuple[str, list[UUID], SupportStatus]
        ],
        gaps: list[str],
        *,
        lease_token: UUID | None = None,
    ) -> None:
        normalized: list[FinalizedClaim] = []
        for item in claims:
            if isinstance(item, FinalizedClaim):
                normalized.append(item)
            else:
                status = item[2] if len(item) == 3 else SupportStatus.SUPPORTED
                normalized.append(
                    FinalizedClaim(
                        text=item[0],
                        evidence_ids=item[1],
                        support_status=status,
                        checker_method="legacy",
                        checker_version="legacy",
                        assessment_state="legacy",
                        assessment_rationale="legacy finalization call",
                    )
                )
        with self._sessions.begin() as session:
            if lease_token is not None:
                self._require_lease(session, run_id, lease_token)
            row = self._run_row(session, run_id)
            if row is None:
                raise NotFoundError("run not found")
            existing = set(
                session.scalars(select(EvidenceRow.id).where(EvidenceRow.run_id == run_id)).all()
            )
            evidence_ids: list[UUID] = []
            for claim in normalized:
                for eid in claim.evidence_ids:
                    if eid not in evidence_ids:
                        evidence_ids.append(eid)
            missing = [eid for eid in evidence_ids if eid not in existing]
            if missing:
                raise ValueError(f"answer references evidence not owned by run: {missing}")
            prior = session.scalars(select(ClaimRow.id).where(ClaimRow.run_id == run_id)).all()
            if prior:
                session.execute(
                    delete(ClaimEvidenceRow).where(ClaimEvidenceRow.claim_id.in_(prior))
                )
                session.execute(delete(ClaimRow).where(ClaimRow.id.in_(prior)))
            labels = {eid: i + 1 for i, eid in enumerate(evidence_ids)}
            answer_claims: list[AnswerClaim] = []
            for claim in normalized:
                claim_row = ClaimRow(
                    run_id=run_id,
                    text=claim.text,
                    support_status=claim.support_status.value,
                    checker_method=claim.checker_method,
                    checker_version=claim.checker_version,
                    assessment_state=claim.assessment_state,
                    assessment_rationale=claim.assessment_rationale,
                )
                session.add(claim_row)
                session.flush()
                citation_labels = []
                for eid in claim.evidence_ids:
                    if labels[eid] not in citation_labels:
                        citation_labels.append(labels[eid])
                    relation = claim.evidence_relations.get(
                        str(eid),
                        "contextualizes"
                        if claim.support_status is SupportStatus.CONFLICTING
                        else "supports",
                    )
                    session.add(
                        ClaimEvidenceRow(
                            claim_id=claim_row.id,
                            evidence_id=eid,
                            relation=relation,
                            rationale=claim.evidence_rationales.get(
                                str(eid), claim.assessment_rationale
                            )[:4000],
                            checker_method=claim.checker_method,
                            checker_version=claim.checker_version,
                        )
                    )
                answer_claims.append(
                    AnswerClaim(
                        text=claim.text,
                        citation_labels=citation_labels,
                        support_status=claim.support_status,
                        checker_method=claim.checker_method,
                        checker_version=claim.checker_version,
                        assessment_state=claim.assessment_state,
                        assessment_rationale=claim.assessment_rationale,
                    )
                )
            block = AnswerBlock(
                id="answer-1",
                markdown=markdown,
                citations=[
                    CitationRef(evidence_id=eid, label=i + 1) for i, eid in enumerate(evidence_ids)
                ],
                claims=answer_claims,
            )
            row.answer_blocks = [block.model_dump(mode="json")]
            row.gaps = gaps
            block_payload = block.model_dump(mode="json")
            # Preserve the M07 event for rolling clients and add the explicit M10 semantic: this
            # payload is complete, server-validated, and safe to replace by block id/version.
            self._append_event(session, run_id, "answer.block", block_payload)
            self._append_event(
                session, run_id, "answer.block.validated", {**block_payload, "version": 1}
            )

    def reserve_provider_usage(
        self,
        *,
        provider: str,
        model: str,
        rpm: int,
        tpm: int,
        rpd: int,
        input_tokens: int,
        run_id: UUID | None = None,
    ) -> UUID:
        """Atomically reserve conservative request/token budget.

        RPD is enforced as a rolling 24-hour ceiling because provider reset semantics can
        differ from the user's local day. This is intentionally stricter than guessing.
        """
        now = datetime.now(UTC)
        minute_start = now - timedelta(minutes=1)
        day_start = now - timedelta(hours=24)
        with self._sessions.begin() as session:
            # Serialize quota reservations per provider/model before reading usage.
            # The lock row is created lazily and then updated on every reservation.
            # PostgreSQL holds a row lock until commit; SQLite obtains a database
            # write lock for the demo/test path. This prevents concurrent workers
            # from both observing the same remaining allowance and oversubscribing it.
            lock_key = {"provider": provider, "model": model}
            if session.get(ProviderQuotaLockRow, lock_key) is None:
                try:
                    with session.begin_nested():
                        session.add(
                            ProviderQuotaLockRow(provider=provider, model=model, touched_at=now)
                        )
                        session.flush()
                except IntegrityError:
                    # Another transaction created the same lock row first.
                    pass
            locked = session.execute(
                update(ProviderQuotaLockRow)
                .where(
                    ProviderQuotaLockRow.provider == provider,
                    ProviderQuotaLockRow.model == model,
                )
                .values(touched_at=now)
            )
            if locked.rowcount != 1:
                raise RuntimeError("provider quota lock could not be acquired")

            minute_requests = (
                session.scalar(
                    select(func.coalesce(func.sum(ProviderUsageRow.requests), 0)).where(
                        ProviderUsageRow.provider == provider,
                        ProviderUsageRow.model == model,
                        ProviderUsageRow.created_at >= minute_start,
                    )
                )
                or 0
            )
            minute_tokens = (
                session.scalar(
                    select(
                        func.coalesce(func.sum(ProviderUsageRow.input_tokens_reserved), 0)
                    ).where(
                        ProviderUsageRow.provider == provider,
                        ProviderUsageRow.model == model,
                        ProviderUsageRow.created_at >= minute_start,
                    )
                )
                or 0
            )
            day_requests = (
                session.scalar(
                    select(func.coalesce(func.sum(ProviderUsageRow.requests), 0)).where(
                        ProviderUsageRow.provider == provider,
                        ProviderUsageRow.model == model,
                        ProviderUsageRow.created_at >= day_start,
                    )
                )
                or 0
            )
            if int(minute_requests) + 1 > rpm:
                raise QuotaExceededError("configured Gemini requests-per-minute ceiling reached")
            if int(minute_tokens) + input_tokens > tpm:
                raise QuotaExceededError("configured Gemini input-token-per-minute ceiling reached")
            if int(day_requests) + 1 > rpd:
                raise QuotaExceededError("configured Gemini rolling daily request ceiling reached")
            usage = ProviderUsageRow(
                provider=provider,
                model=model,
                run_id=run_id,
                requests=1,
                input_tokens_reserved=input_tokens,
                created_at=now,
            )
            session.add(usage)
            session.flush()
            return usage.id

    def reconcile_provider_usage(
        self, usage_id: UUID, *, input_tokens_actual: int | None, output_tokens_actual: int | None
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(ProviderUsageRow, usage_id)
            if row is None:
                raise NotFoundError("provider usage reservation not found")
            row.input_tokens_actual = input_tokens_actual
            row.output_tokens_actual = output_tokens_actual
            row.reconciled_at = datetime.now(UTC)

    def persist_facet_coverage(
        self, run_id: UUID, facets, *, checker_method: str, checker_version: str, lease_token: UUID
    ) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            for facet in facets:
                row = session.scalar(
                    select(FacetCoverageRow)
                    .where(
                        FacetCoverageRow.run_id == run_id, FacetCoverageRow.facet_key == facet.facet
                    )
                    .with_for_update()
                )
                values = {
                    "status": facet.status.value,
                    "supporting_evidence_ids": [
                        str(value) for value in facet.supporting_evidence_ids
                    ],
                    "conflicting_evidence_ids": [
                        str(value) for value in facet.conflicting_evidence_ids
                    ],
                    "rationale": facet.rationale[:4000],
                    "checker_method": checker_method,
                    "checker_version": checker_version,
                    "updated_at": now,
                }
                if row is None:
                    row = FacetCoverageRow(
                        workspace_id=run.workspace_id,
                        run_id=run_id,
                        facet_key=facet.facet,
                        **values,
                    )
                    session.add(row)
                else:
                    for key, value in values.items():
                        setattr(row, key, value)

    def get_research_cache(
        self,
        run_id: UUID,
        *,
        namespace: str,
        cache_key: str,
        policy_version: str,
        lease_token: UUID,
    ) -> dict[str, object] | None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            row = session.scalar(
                select(ResearchCacheRow).where(
                    ResearchCacheRow.workspace_id == run.workspace_id,
                    ResearchCacheRow.namespace == namespace,
                    ResearchCacheRow.cache_key == cache_key,
                    ResearchCacheRow.policy_version == policy_version,
                )
            )
            if row is None:
                return None
            expires_at = (
                row.expires_at
                if row.expires_at.tzinfo is not None
                else row.expires_at.replace(tzinfo=UTC)
            )
            created_at = (
                row.created_at
                if row.created_at.tzinfo is not None
                else row.created_at.replace(tzinfo=UTC)
            )
            retrieved_at = row.retrieved_at
            if retrieved_at is not None and retrieved_at.tzinfo is None:
                retrieved_at = retrieved_at.replace(tzinfo=UTC)
            if expires_at <= now:
                session.delete(row)
                return None
            return {
                "payload": dict(row.payload_json or {}),
                "created_at": created_at,
                "expires_at": expires_at,
                "retrieved_at": retrieved_at,
            }

    def purge_expired_research_cache(self, *, limit: int = 500) -> int:
        """Bounded cache maintenance that is safe to call from a worker heartbeat.

        Expiry is also enforced on reads; this method prevents cold expired rows from
        accumulating forever. It deliberately has no run/workspace argument because it only
        deletes records whose expiry has already passed and returns no tenant data.
        """
        if limit < 1:
            return 0
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            ids = list(
                session.scalars(
                    select(ResearchCacheRow.id)
                    .where(ResearchCacheRow.expires_at <= now)
                    .order_by(ResearchCacheRow.expires_at.asc())
                    .limit(limit)
                )
            )
            if not ids:
                return 0
            session.execute(delete(ResearchCacheRow).where(ResearchCacheRow.id.in_(ids)))
            return len(ids)

    def put_research_cache(
        self,
        run_id: UUID,
        *,
        namespace: str,
        cache_key: str,
        policy_version: str,
        payload: dict[str, object],
        ttl_seconds: int,
        retrieved_at: datetime | None,
        lease_token: UUID,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("research cache ttl must be positive")
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            row = session.scalar(
                select(ResearchCacheRow)
                .where(
                    ResearchCacheRow.workspace_id == run.workspace_id,
                    ResearchCacheRow.namespace == namespace,
                    ResearchCacheRow.cache_key == cache_key,
                    ResearchCacheRow.policy_version == policy_version,
                )
                .with_for_update()
            )
            if row is None:
                row = ResearchCacheRow(
                    workspace_id=run.workspace_id,
                    namespace=namespace,
                    cache_key=cache_key,
                    policy_version=policy_version,
                    payload_json=dict(payload),
                    retrieved_at=retrieved_at,
                    created_at=now,
                    expires_at=expires_at,
                )
                session.add(row)
            else:
                row.payload_json = dict(payload)
                row.retrieved_at = retrieved_at
                row.created_at = now
                row.expires_at = expires_at

    def start_checkpoint(
        self,
        run_id: UUID,
        *,
        step_key: str,
        input_hash: str,
        lease_token: UUID,
        schema_version: int = 1,
    ) -> dict[str, object] | None:
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            row = session.scalar(
                select(RunStepRow)
                .where(
                    RunStepRow.run_id == run_id,
                    RunStepRow.step_key == step_key,
                    RunStepRow.input_hash == input_hash,
                    RunStepRow.schema_version == schema_version,
                )
                .with_for_update()
            )
            if row is not None and row.status == "completed":
                return dict(row.output_json or {})
            if row is None:
                row = RunStepRow(
                    run_id=run_id,
                    workspace_id=run.workspace_id,
                    step_key=step_key,
                    input_hash=input_hash,
                    schema_version=schema_version,
                    lease_token=lease_token,
                )
                session.add(row)
            else:
                row.status = "started"
                row.attempt = int(row.attempt or 0) + 1
                row.lease_token = lease_token
                row.completed_at = None
            return None

    def complete_checkpoint(
        self,
        run_id: UUID,
        *,
        step_key: str,
        input_hash: str,
        output: dict[str, object],
        lease_token: UUID,
        schema_version: int = 1,
    ) -> None:
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            row = session.scalar(
                select(RunStepRow)
                .where(
                    RunStepRow.run_id == run_id,
                    RunStepRow.step_key == step_key,
                    RunStepRow.input_hash == input_hash,
                    RunStepRow.schema_version == schema_version,
                )
                .with_for_update()
            )
            if row is None:
                run = session.get(RunRow, run_id)
                if run is None:
                    raise NotFoundError("run not found")
                row = RunStepRow(
                    run_id=run_id,
                    workspace_id=run.workspace_id,
                    step_key=step_key,
                    input_hash=input_hash,
                    schema_version=schema_version,
                )
                session.add(row)
                session.flush()
            if row.lease_token not in {None, lease_token}:
                raise StaleLeaseError("checkpoint belongs to a different worker lease")
            row.status = "completed"
            row.output_json = output
            row.lease_token = lease_token
            row.completed_at = datetime.now(UTC)
            self._append_event(
                session,
                run_id,
                "run.checkpointed",
                {"step": step_key, "input_hash": input_hash, "schema_version": schema_version},
            )

    def acquire_resource_lease(
        self, run_id: UUID, *, resource_key: str, capacity: int, ttl_seconds: int, lease_token: UUID
    ) -> ResourceLease:
        if capacity < 1 or ttl_seconds < 1:
            raise ValueError("resource lease capacity and ttl must be positive")
        now = datetime.now(UTC)
        until = now + timedelta(seconds=ttl_seconds)
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            run = session.get(RunRow, run_id)
            if run is None:
                raise NotFoundError("run not found")
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                key = int.from_bytes(
                    hashlib.sha256(resource_key.encode()).digest()[:8], "big", signed=True
                )
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            session.execute(
                delete(ResourceLeaseRow).where(
                    ResourceLeaseRow.resource_key == resource_key,
                    ResourceLeaseRow.leased_until <= now,
                )
            )
            occupied = set(
                session.scalars(
                    select(ResourceLeaseRow.slot).where(
                        ResourceLeaseRow.resource_key == resource_key
                    )
                ).all()
            )
            slot = next((value for value in range(capacity) if value not in occupied), None)
            if slot is None:
                raise ResourceCapacityError(f"resource capacity exhausted: {resource_key}")
            token = uuid4()
            session.add(
                ResourceLeaseRow(
                    workspace_id=run.workspace_id,
                    owner_run_id=run_id,
                    resource_key=resource_key,
                    slot=slot,
                    lease_token=token,
                    leased_until=until,
                    created_at=now,
                )
            )
            session.flush()
            return ResourceLease(
                run_id=run_id, resource_key=resource_key, slot=slot, token=token, leased_until=until
            )

    def release_resource_lease(self, resource: ResourceLease) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(ResourceLeaseRow).where(
                    ResourceLeaseRow.lease_token == resource.token,
                    ResourceLeaseRow.owner_run_id == resource.run_id,
                )
            )
            if row is not None:
                session.delete(row)

    def count_run_evidence(self, run_id: UUID) -> int:
        with self._sessions() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(EvidenceRow)
                    .where(EvidenceRow.run_id == run_id)
                )
                or 0
            )

    def finalize_partial_report(
        self, run_id: UUID, *, reason: str, gaps: list[str], lease_token: UUID
    ) -> bool:
        with self._sessions.begin() as session:
            self._require_lease(session, run_id, lease_token)
            row = session.get(RunRow, run_id)
            evidence = session.scalars(
                select(EvidenceRow)
                .where(EvidenceRow.run_id == run_id)
                .order_by(EvidenceRow.captured_at)
                .limit(20)
            ).all()
            if row is None or not evidence:
                return False
            block = AnswerBlock(
                id="partial-evidence-report",
                markdown=f"### Partial evidence report\n\nARES stopped before a complete checked answer could be produced. Reason: {reason}.",
                citations=[
                    CitationRef(evidence_id=e.id, label=i + 1) for i, e in enumerate(evidence)
                ],
                claims=[],
            )
            row.answer_blocks = [block.model_dump(mode="json")]
            row.gaps = list(dict.fromkeys([*gaps, reason]))
            self._append_event(session, run_id, "answer.block", block.model_dump(mode="json"))
            return True

    def register_worker(
        self, instance_name: str, *, capabilities: dict[str, object] | None = None
    ) -> UUID:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = WorkerInstanceRow(
                instance_name=instance_name[:160],
                state="active",
                started_at=now,
                last_seen_at=now,
                capabilities_json=dict(capabilities or {}),
            )
            session.add(row)
            session.flush()
            return row.id

    def heartbeat_worker(
        self,
        worker_id: UUID,
        *,
        state: str = "active",
        capabilities: dict[str, object] | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(WorkerInstanceRow, worker_id)
            if row is None:
                raise NotFoundError("worker registration not found")
            row.state = state[:24]
            row.last_seen_at = datetime.now(UTC)
            if capabilities is not None:
                row.capabilities_json = dict(capabilities)

    def stop_worker(self, worker_id: UUID) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.get(WorkerInstanceRow, worker_id)
            if row is not None:
                row.state = "stopped"
                row.last_seen_at = now
                row.stopped_at = now

    def get_worker_profiles(self, *, stale_seconds: int = 45) -> dict[str, int]:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
        counts = {"research": 0, "media": 0, "combined": 0}
        with self._sessions() as session:
            rows = session.scalars(select(WorkerInstanceRow)).all()
            for row in rows:
                seen = (
                    row.last_seen_at
                    if row.last_seen_at.tzinfo is not None
                    else row.last_seen_at.replace(tzinfo=UTC)
                )
                if row.state not in {"active", "draining"} or seen < cutoff:
                    continue
                profile = row.instance_name.rsplit(":", 1)[-1]
                if profile in counts:
                    counts[profile] += 1
        return counts

    def get_worker_capabilities(self, *, stale_seconds: int = 45) -> dict[str, bool]:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
        combined: dict[str, bool] = {}
        with self._sessions() as session:
            rows = session.scalars(select(WorkerInstanceRow)).all()
            for row in rows:
                seen = (
                    row.last_seen_at
                    if row.last_seen_at.tzinfo is not None
                    else row.last_seen_at.replace(tzinfo=UTC)
                )
                if row.state not in {"active", "draining"} or seen < cutoff:
                    continue
                for name, value in dict(row.capabilities_json or {}).items():
                    if isinstance(value, bool):
                        combined[str(name)] = combined.get(str(name), False) or value
        return combined

    def get_worker_fleet(self, *, stale_seconds: int = 45) -> dict[str, int]:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
        with self._sessions() as session:
            rows = session.scalars(select(WorkerInstanceRow)).all()
            total = len(rows)
            active = draining = stale = 0
            for row in rows:
                seen = (
                    row.last_seen_at
                    if row.last_seen_at.tzinfo is not None
                    else row.last_seen_at.replace(tzinfo=UTC)
                )
                if row.state in {"active", "draining"} and seen < cutoff:
                    stale += 1
                elif row.state == "draining":
                    draining += 1
                elif row.state == "active":
                    active += 1
            return {"total": total, "active": active, "draining": draining, "stale": stale}

    def finish_job(self, lease: JobLease, *, final_state: str = "done") -> None:
        with self._sessions.begin() as session:
            row = self._require_lease(session, lease.run_id, lease.token)
            row.state = final_state
            row.leased_until = None
            row.lease_token = None

    def get_run_quality(self, run_id: UUID) -> RunQualityView:
        with self._sessions() as session:
            run = self._run_row(session, run_id)
            if run is None:
                raise NotFoundError("run not found")
            claim_rows = session.scalars(select(ClaimRow).where(ClaimRow.run_id == run_id)).all()
            evidence_rows = session.scalars(
                select(EvidenceRow).where(EvidenceRow.run_id == run_id)
            ).all()
            source_rows = session.scalars(select(SourceRow).where(SourceRow.run_id == run_id)).all()
            facet_rows = session.scalars(
                select(FacetCoverageRow)
                .where(FacetCoverageRow.run_id == run_id)
                .order_by(FacetCoverageRow.facet_key.asc())
            ).all()
            relation_rows = session.execute(
                select(ClaimEvidenceRow.relation, func.count())
                .join(ClaimRow, ClaimRow.id == ClaimEvidenceRow.claim_id)
                .where(ClaimRow.run_id == run_id)
                .group_by(ClaimEvidenceRow.relation)
            ).all()
            relation_edges = session.execute(
                select(ClaimEvidenceRow, ClaimRow.text)
                .join(ClaimRow, ClaimRow.id == ClaimEvidenceRow.claim_id)
                .where(ClaimRow.run_id == run_id)
                .order_by(ClaimRow.id, ClaimEvidenceRow.id)
            ).all()
            events = session.scalars(
                select(RunEventRow)
                .where(RunEventRow.run_id == run_id)
                .order_by(RunEventRow.seq.asc())
            ).all()

            support_counts: dict[str, int] = {}
            for claim in claim_rows:
                support_counts[claim.support_status] = (
                    support_counts.get(claim.support_status, 0) + 1
                )
            evidence_relation_counts = {
                str(relation): int(count) for relation, count in relation_rows
            }
            evidence_relation_views = [
                ClaimEvidenceRelationView(
                    claim_id=edge.claim_id,
                    claim_text=claim_text,
                    evidence_id=edge.evidence_id,
                    relation=edge.relation,
                    rationale=edge.rationale,
                    checker_method=edge.checker_method,
                    checker_version=edge.checker_version,
                )
                for edge, claim_text in relation_edges
                if edge.relation in {"supports", "contradicts", "contextualizes"}
            ]
            source_kind_counts: dict[str, int] = {}
            provider_counts: dict[str, int] = {}
            source_group_keys: set[str] = set()
            source_origin_by_id: dict[UUID, UUID] = {}
            for source in source_rows:
                source_kind_counts[source.source_kind] = (
                    source_kind_counts.get(source.source_kind, 0) + 1
                )
                provider_counts[source.provider] = provider_counts.get(source.provider, 0) + 1
                origin = source.origin_group_id or source.id
                source_origin_by_id[source.id] = origin
                source_group_keys.add(str(origin))

            existing_evidence = {row.id for row in evidence_rows}
            evidence_by_id = {row.id: row for row in evidence_rows}
            facet_views: list[RunFacetView] = []
            for facet in facet_rows:
                supporting = [UUID(value) for value in (facet.supporting_evidence_ids or [])]
                conflicting = [UUID(value) for value in (facet.conflicting_evidence_ids or [])]
                origins = {
                    source_origin_by_id.get(
                        evidence_by_id[evidence_id].source_id, evidence_by_id[evidence_id].source_id
                    )
                    for evidence_id in supporting + conflicting
                    if evidence_id in evidence_by_id
                }
                facet_views.append(
                    RunFacetView(
                        facet_key=facet.facet_key,
                        status=facet.status,
                        supporting_evidence_ids=supporting,
                        conflicting_evidence_ids=conflicting,
                        independent_origin_count=len(origins),
                        rationale=facet.rationale,
                        checker_method=facet.checker_method,
                        checker_version=facet.checker_version,
                    )
                )
            resolved = 0
            referenced = 0
            for value in run.answer_blocks or []:
                block = AnswerBlock.model_validate(value)
                by_label = {citation.label: citation.evidence_id for citation in block.citations}
                for claim in block.claims:
                    for label in claim.citation_labels:
                        referenced += 1
                        evidence_id = by_label.get(label)
                        if evidence_id is not None and evidence_id in existing_evidence:
                            resolved += 1
            citation_resolution_rate = resolved / referenced if referenced else 0.0

            cited_claim_ids = set(
                session.scalars(
                    select(ClaimEvidenceRow.claim_id)
                    .join(ClaimRow, ClaimRow.id == ClaimEvidenceRow.claim_id)
                    .where(ClaimRow.run_id == run_id)
                ).all()
            )
            claim_citation_rate = len(cited_claim_ids) / len(claim_rows) if claim_rows else 0.0
            supported_claims = support_counts.get(SupportStatus.SUPPORTED.value, 0)
            supported_claim_rate = supported_claims / len(claim_rows) if claim_rows else 0.0

            stage_timings: dict[str, float] = {}
            risky = 0
            duplicates_removed = 0
            first_claimed_at: datetime | None = None
            terminal_at: datetime | None = None
            for event in events:
                if event.event_type == "stage.timing":
                    stage = str(event.payload.get("stage", "unknown"))
                    duration = event.payload.get("duration_ms", 0)
                    try:
                        stage_timings[stage] = round(
                            stage_timings.get(stage, 0.0) + float(duration), 3
                        )
                    except (TypeError, ValueError):
                        pass
                elif event.event_type == "security.content_risk":
                    risky += 1
                elif event.event_type == "sources.deduplicated":
                    try:
                        duplicates_removed += int(event.payload.get("duplicates_removed", 0))
                    except (TypeError, ValueError):
                        pass
                if event.event_type == "job.claimed" and first_claimed_at is None:
                    first_claimed_at = event.created_at
                if event.event_type in {
                    "run.completed",
                    "run.partial",
                    "run.failed",
                    "run.cancelled",
                }:
                    terminal_at = event.created_at

            queue_wait_ms = None
            if first_claimed_at is not None:
                queue_wait_ms = round(
                    max(0.0, (first_claimed_at - run.created_at).total_seconds() * 1000), 3
                )
            run_elapsed_ms = None
            if terminal_at is not None:
                run_elapsed_ms = round(
                    max(0.0, (terminal_at - run.created_at).total_seconds() * 1000), 3
                )

            return RunQualityView(
                run_id=run_id,
                claim_count=len(claim_rows),
                evidence_count=len(evidence_rows),
                source_count=len(source_rows),
                distinct_source_group_count=len(source_group_keys),
                citation_resolution_rate=citation_resolution_rate,
                claim_citation_rate=claim_citation_rate,
                supported_claim_rate=supported_claim_rate,
                support_counts=support_counts,
                evidence_relation_counts=evidence_relation_counts,
                evidence_relations=evidence_relation_views,
                facets=facet_views,
                source_kind_counts=source_kind_counts,
                provider_counts=provider_counts,
                risky_source_events=risky,
                duplicate_sources_removed=duplicates_removed,
                stage_timings_ms=stage_timings,
                queue_wait_ms=queue_wait_ms,
                run_elapsed_ms=run_elapsed_ms,
                gaps_count=len(run.gaps or []),
            )

    @staticmethod
    def _visualization_view(
        row: VisualizationRow, dataset: VisualizationDatasetRow
    ) -> VisualizationView:
        return VisualizationView(
            id=row.id,
            run_id=row.run_id,
            dataset_id=row.dataset_id,
            kind=row.kind,
            title=row.title,
            description=row.description,
            schema_version=row.schema_version,
            dataset=dict(dataset.dataset_json or {}),
            approved_spec=VisualizationSpec.model_validate(row.approved_spec_json or {}),
            data_lineage=[
                VisualizationLineageRef.model_validate(value)
                for value in (dataset.lineage_json or [])
            ],
            export_metadata=dict(row.export_metadata_json or {}),
            created_at=row.created_at,
        )

    def save_visualization(self, run_id: UUID, draft: VisualizationDraft) -> VisualizationView:
        """Persist one backend-approved visualization idempotently.

        Persistence is a provenance boundary, not just a serializer: the bounded dataset
        schema is revalidated here, every embedded evidence/source ID must be represented
        by lineage, and every lineage reference must resolve to evidence from this exact
        run with matching source, segment and locator. This prevents future callers from
        smuggling cross-run or cross-workspace references into a visual artifact.
        """
        dataset_json, dataset_evidence_ids, dataset_source_ids = validate_visualization_dataset(
            draft.kind, draft.dataset
        )
        lineage_by_evidence = {item.evidence_id: item for item in draft.lineage}
        if len(lineage_by_evidence) != len(draft.lineage):
            raise ValueError("visualization lineage evidence ids must be unique")
        if not dataset_evidence_ids.issubset(lineage_by_evidence):
            raise ValueError("visualization dataset references evidence missing from lineage")
        lineage_source_ids = {item.source_id for item in draft.lineage}
        if not dataset_source_ids.issubset(lineage_source_ids):
            raise ValueError("visualization dataset references sources missing from lineage")

        lineage_json = [item.model_dump(mode="json") for item in draft.lineage]
        dataset_payload = json.dumps(
            {"dataset": dataset_json, "lineage": lineage_json},
            sort_keys=True,
            separators=(",", ":"),
        )
        content_hash = hashlib.sha256(dataset_payload.encode()).hexdigest()
        spec_json = draft.spec.model_dump(mode="json")
        spec_payload = json.dumps(
            {
                "kind": draft.kind.value,
                "title": draft.title,
                "description": draft.description,
                "spec": spec_json,
                "dataset_hash": content_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        spec_hash = hashlib.sha256(spec_payload.encode()).hexdigest()

        with self._sessions.begin() as session:
            run = self._run_row(session, run_id)
            if run is None:
                raise NotFoundError("run not found")

            if draft.lineage:
                evidence_rows = session.scalars(
                    select(EvidenceRow).where(
                        EvidenceRow.run_id == run_id,
                        EvidenceRow.id.in_(lineage_by_evidence),
                    )
                ).all()
                evidence_by_id = {row.id: row for row in evidence_rows}
                if set(evidence_by_id) != set(lineage_by_evidence):
                    raise ValueError(
                        "visualization lineage must resolve to evidence from the same run"
                    )
                for evidence_id, ref in lineage_by_evidence.items():
                    evidence = evidence_by_id[evidence_id]
                    if evidence.source_id != ref.source_id:
                        raise ValueError(
                            "visualization lineage source does not match persisted evidence"
                        )
                    if evidence.segment_id != ref.segment_id:
                        raise ValueError(
                            "visualization lineage segment does not match persisted evidence"
                        )
                    if evidence.locator != ref.locator:
                        raise ValueError(
                            "visualization lineage locator does not match persisted evidence"
                        )

            dataset = session.scalar(
                select(VisualizationDatasetRow).where(
                    VisualizationDatasetRow.run_id == run_id,
                    VisualizationDatasetRow.dataset_kind == draft.kind.value,
                    VisualizationDatasetRow.content_hash == content_hash,
                )
            )
            if dataset is None:
                dataset = VisualizationDatasetRow(
                    workspace_id=run.workspace_id,
                    run_id=run_id,
                    schema_version=1,
                    dataset_kind=draft.kind.value,
                    dataset_json=dataset_json,
                    lineage_json=lineage_json,
                    content_hash=content_hash,
                )
                session.add(dataset)
                session.flush()

            row = session.scalar(
                select(VisualizationRow).where(
                    VisualizationRow.run_id == run_id,
                    VisualizationRow.kind == draft.kind.value,
                    VisualizationRow.spec_hash == spec_hash,
                )
            )
            if row is None:
                row = VisualizationRow(
                    workspace_id=run.workspace_id,
                    run_id=run_id,
                    dataset_id=dataset.id,
                    schema_version=1,
                    kind=draft.kind.value,
                    title=draft.title,
                    description=draft.description,
                    approved_spec_json=spec_json,
                    spec_hash=spec_hash,
                    export_metadata_json=draft.export_metadata,
                )
                session.add(row)
                session.flush()
            return self._visualization_view(row, dataset)

    def list_visualizations(self, run_id: UUID) -> list[VisualizationView]:
        with self._sessions() as session:
            if self._run_row(session, run_id) is None:
                raise NotFoundError("run not found")
            rows = session.execute(
                select(VisualizationRow, VisualizationDatasetRow)
                .join(
                    VisualizationDatasetRow,
                    VisualizationDatasetRow.id == VisualizationRow.dataset_id,
                )
                .where(VisualizationRow.run_id == run_id)
                .order_by(VisualizationRow.created_at.asc(), VisualizationRow.id.asc())
            ).all()
            return [self._visualization_view(row, dataset) for row, dataset in rows]

    def list_run_numeric_table_points(self, run_id: UUID) -> list[NumericTablePointCandidate]:
        """Return only directly cited, normalized numeric table cells for a run.

        Raw text is never parsed here. A point is eligible only when ingestion produced a
        finite numeric ``normalized_value_json`` and the exact segment was promoted into
        run evidence. This keeps chart data on the same provenance path as the answer.
        """
        with self._sessions() as session:
            if self._run_row(session, run_id) is None:
                raise NotFoundError("run not found")
            records = session.execute(
                select(EvidenceRow, DocumentTableCellRow, DocumentTableRow)
                .join(
                    DocumentTableCellRow, DocumentTableCellRow.segment_id == EvidenceRow.segment_id
                )
                .join(DocumentTableRow, DocumentTableRow.id == DocumentTableCellRow.table_id)
                .where(EvidenceRow.run_id == run_id)
                .order_by(
                    DocumentTableRow.id,
                    DocumentTableCellRow.row_index,
                    DocumentTableCellRow.column_index,
                )
            ).all()
            if not records:
                return []
            table_ids = {table.id for _, _, table in records}
            all_cells = session.scalars(
                select(DocumentTableCellRow)
                .where(DocumentTableCellRow.table_id.in_(table_ids))
                .order_by(
                    DocumentTableCellRow.table_id,
                    DocumentTableCellRow.row_index,
                    DocumentTableCellRow.column_index,
                )
            ).all()
            by_table: dict[UUID, list[DocumentTableCellRow]] = {}
            for cell in all_cells:
                by_table.setdefault(cell.table_id, []).append(cell)

            def as_number(value: object | None) -> float | None:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return None
                numeric = float(value)
                return numeric if math.isfinite(numeric) else None

            def label_for(cell: DocumentTableCellRow, table: DocumentTableRow) -> str:
                cells = by_table.get(table.id, [])
                row_header = next(
                    (
                        other.raw_text.strip()
                        for other in reversed(cells)
                        if other.row_index == cell.row_index
                        and other.column_index < cell.column_index
                        and other.is_header
                        and other.raw_text.strip()
                    ),
                    "",
                )
                if not row_header:
                    row_header = next(
                        (
                            other.raw_text.strip()
                            for other in cells
                            if other.row_index == cell.row_index
                            and other.column_index == 0
                            and other.id != cell.id
                            and other.raw_text.strip()
                        ),
                        "",
                    )
                column_header = next(
                    (
                        other.raw_text.strip()
                        for other in reversed(cells)
                        if other.column_index == cell.column_index
                        and other.row_index < cell.row_index
                        and other.is_header
                        and other.raw_text.strip()
                    ),
                    "",
                )
                parts = [part for part in (row_header, column_header) if part]
                return (
                    " · ".join(parts)
                    or f"{table.table_key} R{cell.row_index + 1} C{cell.column_index + 1}"
                )

            output: list[NumericTablePointCandidate] = []
            for evidence, cell, table in records:
                value = as_number(cell.normalized_value_json)
                if value is None or evidence.segment_id is None:
                    continue
                output.append(
                    NumericTablePointCandidate(
                        evidence_id=evidence.id,
                        source_id=evidence.source_id,
                        segment_id=evidence.segment_id,
                        table_id=table.id,
                        table_key=table.table_key,
                        row=cell.row_index,
                        column=cell.column_index,
                        label=label_for(cell, table),
                        value=value,
                        unit=cell.unit,
                    )
                )
            return output

    def get_evidence(self, evidence_id: UUID) -> EvidenceView:
        with self._sessions() as session:
            stmt = (
                select(EvidenceRow)
                .join(RunRow, RunRow.id == EvidenceRow.run_id)
                .where(EvidenceRow.id == evidence_id)
            )
            workspace_id = self._visible_workspace_id()
            if workspace_id is not None:
                stmt = stmt.where(RunRow.workspace_id == workspace_id)
            row = session.scalar(stmt)
            if row is None:
                raise NotFoundError("evidence not found")
            source = row.source
            asset_id = None
            asset_name = None
            asset_mime_type = None
            locator_data = None
            asset_content_url = None
            if row.segment_id is not None:
                segment = session.get(EvidenceSegmentRow, row.segment_id)
                if segment is not None:
                    extraction = session.get(ExtractionVersionRow, segment.extraction_version_id)
                    if extraction is not None:
                        asset_id = extraction.asset_version_id
                        asset = session.get(AssetVersionRow, asset_id)
                        if asset is not None:
                            asset_name = asset.original_name
                            asset_mime_type = asset.mime_type
                        locator_data = dict(segment.locator_json or {})
                        asset_content_url = f"/api/v2/assets/{asset_id}/content"
            return EvidenceView(
                id=row.id,
                source=SourceView(
                    id=source.id,
                    title=source.title,
                    url=source.url,
                    domain=source.domain,
                    fetched_at=source.fetched_at,
                    extraction_method=source.extraction_method,
                    provider=source.provider,
                    source_kind=source.source_kind,
                    canonical_identifier=source.canonical_identifier,
                    published_at=source.published_at,
                    discovery_rank=source.discovery_rank,
                    snippet=source.snippet,
                ),
                document_version_id=row.document_version_id,
                segment_id=row.segment_id,
                asset_id=asset_id,
                asset_name=asset_name,
                asset_mime_type=asset_mime_type,
                locator_data=locator_data,
                asset_content_url=asset_content_url,
                text=row.text,
                char_start=row.char_start,
                char_end=row.char_end,
                page_start=row.page_start,
                page_end=row.page_end,
                locator=row.locator,
                support_status=SupportStatus(row.support_status),
                captured_at=row.captured_at,
                content_hash=source.content_hash,
            )

    def list_events(self, run_id: UUID, after: int = 0, *, limit: int = 200) -> list[EventEnvelope]:
        if after < 0:
            raise ValueError("event cursor cannot be negative")
        if not 1 <= limit <= 1000:
            raise ValueError("event page limit must be between 1 and 1000")
        with self._sessions() as session:
            if self._run_row(session, run_id) is None:
                raise NotFoundError("run not found")
            rows = session.scalars(
                select(RunEventRow)
                .where(RunEventRow.run_id == run_id, RunEventRow.seq > after)
                .order_by(RunEventRow.seq.asc())
                .limit(limit)
            ).all()
            return [
                EventEnvelope(
                    schema_version=row.schema_version,
                    run_id=row.run_id,
                    seq=row.seq,
                    event_type=row.event_type,
                    at=row.created_at,
                    payload=row.payload,
                )
                for row in rows
            ]

    def _require_lease(self, session: Session, run_id: UUID, token: UUID) -> JobRow:
        row = session.scalar(select(JobRow).where(JobRow.run_id == run_id))
        if row is None:
            raise NotFoundError("job not found")
        if row.state != "running" or row.lease_token != token:
            raise StaleLeaseError("worker lease is stale")
        if row.leased_until is None:
            raise StaleLeaseError("worker lease has expired")
        leased_until = row.leased_until
        if leased_until.tzinfo is None:
            leased_until = leased_until.replace(tzinfo=UTC)
        if leased_until < datetime.now(UTC):
            raise StaleLeaseError("worker lease has expired")
        return row

    def _append_event(
        self, session: Session, run_id: UUID, event_type: str, payload: dict[str, object]
    ) -> None:
        row = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
        if row is None:
            raise NotFoundError("run not found")
        latest = max(
            int(row.last_seq or 0),
            int(
                session.scalar(
                    select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == run_id)
                )
                or 0
            ),
        )
        row.last_seq = latest + 1
        session.add(
            RunEventRow(
                run_id=run_id,
                seq=row.last_seq,
                schema_version=2,
                event_type=event_type,
                payload=payload,
            )
        )

    @staticmethod
    def _snapshot(row: RunRow) -> RunSnapshot:
        return RunSnapshot(
            id=row.id,
            conversation_id=row.conversation_id,
            query=row.query,
            mode=RunMode(row.mode),
            source_scope=list(row.source_scope or []),
            document_ids=[UUID(value) for value in (row.document_ids or [])],
            date_window=row.date_window,
            deadline_at=row.deadline_at,
            budget_version=row.budget_version or "legacy",
            usage_ledger={str(k): int(v) for k, v in (row.usage_ledger or {}).items()},
            last_seq=int(row.last_seq or 0),
            status=RunStatus(row.status),
            answer_blocks=[AnswerBlock.model_validate(value) for value in row.answer_blocks or []],
            gaps=list(row.gaps or []),
            error_code=row.error_code,
            error_message=row.error_message,
            cancellation_requested=row.cancellation_requested,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
