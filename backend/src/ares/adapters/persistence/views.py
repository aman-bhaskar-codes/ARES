from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select

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
    EvidenceRow,
    EvidenceSegmentRow,
    ExtractionVersionRow,
    IngestionEventRow,
    IngestionJobRow,
    MediaFrameRow,
    MediaTrackRow,
    ResearchCacheRow,
    FacetCoverageRow,
    RunEventRow,
    RunRow,
    SourceRow,
    UserDocumentRow,
    WorkerInstanceRow,
    VisualizationDatasetRow,
    VisualizationRow,
)
from ares.domain.assets import (
    AssetView,
    EvidenceLocator,
    IngestionEventEnvelope,
    IngestionView,
    MediaFrameView,
    MediaStoryboardView,
    MediaTrackView,
    SegmentView,
    TableCellView,
    TableView,
)
from ares.domain.models import (
    AnswerBlock,
    ConversationView,
    EventEnvelope,
    EvidenceView,
    DocumentView,
    RunCreate,
    ClaimEvidenceRelationView,
    RunFacetView,
    RunQualityView,
    RunSnapshot,
    SourceView,
    SupportStatus,
)
from ares.domain.visualizations import (
    NumericTablePointCandidate,
    VisualizationView,
)


from ares.ports.repositories import NotFoundError, IdempotencyConflictError, StaleLeaseError, QuotaExceededError, RunAdmissionError, RunBudgetExceededError, RunAuthorizationError, ResourceCapacityError, JobLease, ResourceLease, IngestionLease, IngestionPublication


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


from ares.adapters.persistence.base import SqlRepositoryBase


class SqlViewRepository(SqlRepositoryBase):
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

    def get_run(self, run_id: UUID) -> RunSnapshot:
        with self._sessions() as session:
            row = self._run_row(session, run_id)
            if row is None:
                raise NotFoundError("run not found")
            return self._snapshot(row)

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

    def get_ingestion_asset_for_worker(self, lease: IngestionLease) -> AssetVersionRow:
        with self._sessions() as session:
            row = self._require_ingestion_lease(session, lease.ingestion_id, lease.token)
            asset = session.get(AssetVersionRow, row.asset_version_id)
            if asset is None or asset.workspace_id != row.workspace_id:
                raise RunAuthorizationError("ingestion asset is missing or unauthorized")
            session.expunge(asset)
            return asset

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
