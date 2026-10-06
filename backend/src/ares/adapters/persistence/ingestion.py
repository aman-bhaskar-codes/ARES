from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, update

from ares.adapters.db import (
    AssetRenditionRow,
    AssetVersionRow,
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
    UserDocumentRow,
    WorkspaceMembershipRow,
)
from ares.domain.assets import (
    AssetStatus,
    AssetView,
    ExtractionSegmentDraft,
    ExtractionTableDraft,
    IngestionStage,
    IngestionStatus,
    IngestionView,
)
from ares.domain.models import (
    DocumentStatus,
    RunCreate,
)
from ares.application.documents import PreparedChunk


from ares.ports.repositories import NotFoundError, IdempotencyConflictError, StaleLeaseError, QuotaExceededError, RunAdmissionError, RunBudgetExceededError, RunAuthorizationError, ResourceCapacityError, JobLease, ResourceLease, IngestionLease, IngestionPublication


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


from ares.adapters.persistence.base import SqlRepositoryBase


class SqlIngestionRepository(SqlRepositoryBase):
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
