from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ares.adapters.db import (
    AssetRenditionRow,
    AssetVersionRow,
    ArtifactRow,
    ClaimEvidenceRow,
    ClaimRow,
    ConversationRow,
    EvidenceRow,
    ExtractionVersionRow,
    IngestionEventRow,
    IngestionJobRow,
    MediaFrameRow,
    MediaTrackRow,
    JobRow,
    ProviderQuotaLockRow,
    FacetCoverageRow,
    ProviderUsageRow,
    RunEventRow,
    RunRow,
    RunStepRow,
    UserDocumentRow,
    UserRow,
    WorkspaceRow,
    WorkspaceMembershipRow,
    VisualizationDatasetRow,
    VisualizationRow,
)
from ares.domain.assets import (
    AssetStatus,
    AssetView,
    IngestionStage,
    IngestionStatus,
    IngestionView,
    MediaFrameDraft,
    MediaTrackDraft,
)
from ares.domain.models import (
    AnswerClaim,
    AnswerBlock,
    CitationRef,
    DocumentStatus,
    DocumentView,
    FinalizedClaim,
    RunCreate,
    RunMode,
    RunSnapshot,
    RunStatus,
    SupportStatus,
)
from ares.domain.visualizations import (
    VisualizationLineageRef,
    VisualizationSpec,
    VisualizationView,
)
from ares.application.identity import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Principal,
    WorkspaceRole,
    current_principal,
    local_principal,
)
from ares.domain.state_machine import assert_transition


from ares.ports.repositories import NotFoundError, StaleLeaseError, QuotaExceededError, RunAuthorizationError, JobLease, IngestionLease
from ares.domain.research import AnswerOutline, RunAssessment


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class SqlRepositoryBase:
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

    def finalize_answer(
        self,
        run_id: UUID,
        markdown: str,
        claims: list[
            FinalizedClaim | tuple[str, list[UUID]] | tuple[str, list[UUID], SupportStatus]
        ],
        gaps: list[str],
        *,
        related_questions: list[str] | None = None,
        outline: AnswerOutline | None = None,
        assessment: RunAssessment | None = None,
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
            if related_questions:
                row.related_questions = related_questions
            if outline:
                row.outline = outline.model_dump(mode="json")
            if assessment:
                row.assessment = assessment.model_dump(mode="json")
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
        output_tokens: int,
        cost_usd: float,
        max_daily_spend_usd: float | None = None,
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

            if max_daily_spend_usd is not None:
                day_spend = (
                    session.scalar(
                        select(func.coalesce(func.sum(ProviderUsageRow.cost_usd_reserved), 0.0)).where(
                            ProviderUsageRow.provider == provider,
                            ProviderUsageRow.created_at >= day_start,
                        )
                    )
                    or 0.0
                )
                if float(day_spend) + cost_usd > max_daily_spend_usd:
                    raise QuotaExceededError("configured daily spend ceiling reached")

            usage = ProviderUsageRow(
                provider=provider,
                model=model,
                run_id=run_id,
                requests=1,
                input_tokens_reserved=input_tokens,
                output_tokens_reserved=output_tokens,
                cost_usd_reserved=cost_usd,
                created_at=now,
            )
            session.add(usage)
            session.flush()
            return usage.id

    def reconcile_provider_usage(
        self,
        usage_id: UUID,
        *,
        input_tokens_actual: int | None,
        output_tokens_actual: int | None,
        cost_usd_actual: float | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(ProviderUsageRow, usage_id)
            if row is None:
                raise NotFoundError("provider usage reservation not found")
            row.input_tokens_actual = input_tokens_actual
            row.output_tokens_actual = output_tokens_actual
            if cost_usd_actual is not None:
                row.cost_usd_actual = cost_usd_actual
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
            def literal(value: str) -> str:
                return re.sub(r"([\\`*_{}\[\]()#+.!<>|~-])", r"\\\1", value)

            passages = []
            for index, item in enumerate(evidence, 1):
                excerpt = " ".join(item.text.split())[:700]
                passages.append(f"#### Evidence passage [{index}]\n\n> {literal(excerpt)}")
            block = AnswerBlock(
                id="partial-evidence-report",
                markdown=(
                    f"### Retrieved evidence\n\nA generated answer is unavailable: {literal(reason)}. "
                    "These are excerpts from retrieved sources, not independently verified conclusions.\n\n"
                    + "\n\n".join(passages)
                ),
                citations=[
                    CitationRef(evidence_id=e.id, label=i + 1) for i, e in enumerate(evidence)
                ],
                claims=[],
            )
            row.answer_blocks = [block.model_dump(mode="json")]
            row.gaps = list(dict.fromkeys([*gaps, reason]))
            self._append_event(session, run_id, "answer.block", block.model_dump(mode="json"))
            return True

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
            model_provider=row.model_provider,
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
            plugins=list(row.plugins or []),
            related_questions=list(row.related_questions or []),
            error_code=row.error_code,
            error_message=row.error_message,
            cancellation_requested=row.cancellation_requested,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
