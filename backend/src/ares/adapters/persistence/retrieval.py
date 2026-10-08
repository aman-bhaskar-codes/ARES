from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, text

from ares.adapters.db import (
    RetrievalProfileRow,
    RetrievalTraceRow,
    AssetRenditionRow,
    AssetVersionRow,
    DocumentChunkRow,
    DocumentEmbeddingRow,
    DocumentVersionRow,
    EvidenceRow,
    MediaFrameRow,
    MediaTrackRow,
    ResearchCacheRow,
    RunRow,
    SourceRow,
    UserDocumentRow,
)
from ares.domain.models import (
    DocumentStatus,
    DocumentTextCreate,
    DocumentView,
    FetchedDocument,
    RunCreate,
    SupportStatus,
)
from ares.domain.research import EvidenceCandidate, EvidencePacket, RetrievalTrace
from ares.application.documents import PreparedChunk
from ares.application.source_identity import source_origin_group


from ares.ports.repositories import NotFoundError, RunAuthorizationError, IngestionLease
from ares.adapters.persistence.base import SqlRepositoryBase


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()




class SqlRetrievalRepository(SqlRepositoryBase):
    def store_retrieval_trace(self, trace: RetrievalTrace) -> None:
        principal = self._request_principal()
        with self._sessions.begin() as session:
            self._ensure_local_identity(session, principal)
            row = RetrievalTraceRow(
                id=trace.id,
                workspace_id=principal.workspace_id,
                query_hash=trace.query_hash,
                profile_id=trace.profile_id,
                filters=trace.filters,
                candidate_ids=trace.candidate_ids,
                candidate_ranks=trace.candidate_ranks,
                selected_packet_ids=trace.selected_packet_ids,
                stage_times=trace.stage_times,
                cache_freshness=trace.cache_freshness,
                coverage_gaps=trace.coverage_gaps,
                policy_revision=trace.policy_revision,
                created_at=trace.created_at,
            )
            session.add(row)

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

    def store_chunk_embeddings(
        self, *, profile_id: UUID | None = None, model_id: str, dimensions: int, embeddings: list[tuple[UUID, list[float]]]
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
                            profile_id=profile_id,
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
                            INSERT INTO document_embeddings_pg (chunk_id, profile_id, model_id, dimensions, embedding)
                            VALUES (:chunk_id, :profile_id, :model_id, :dimensions, CAST(:embedding AS vector))
                            ON CONFLICT (chunk_id, model_id, dimensions)
                            DO UPDATE SET embedding = EXCLUDED.embedding
                            """
                        ),
                        {
                            "chunk_id": chunk_id,
                            "profile_id": profile_id,
                            "model_id": model_id,
                            "dimensions": dimensions,
                            "embedding": literal,
                        },
                    )

    
    def get_retrieval_profile_by_model(self, model_id: str) -> dict | None:
        with self._sessions.begin() as session:
            # For now, just grab the latest matching model ID
            row = session.scalar(select(RetrievalProfileRow).where(RetrievalProfileRow.model_id == model_id).order_by(RetrievalProfileRow.created_at.desc()))
            if row is None:
                return None
            return {
                "id": row.id,
                "profile_key": row.profile_key,
                "provider": row.provider,
                "model_id": row.model_id,
                "artifact_digest": row.artifact_digest,
                "tokenizer_version": row.tokenizer_version,
                "dimensions": row.dimensions,
                "distance_metric": row.distance_metric,
                "language_coverage": row.language_coverage,
                "chunk_policy": row.chunk_policy,
                "extraction_revision": row.extraction_revision,
            }

    def get_retrieval_profile(self, profile_key: str) -> dict | None:
        with self._sessions.begin() as session:
            row = session.scalar(select(RetrievalProfileRow).where(RetrievalProfileRow.profile_key == profile_key))
            if row is None:
                return None
            return {
                "id": row.id,
                "profile_key": row.profile_key,
                "provider": row.provider,
                "model_id": row.model_id,
                "artifact_digest": row.artifact_digest,
                "tokenizer_version": row.tokenizer_version,
                "dimensions": row.dimensions,
                "distance_metric": row.distance_metric,
                "language_coverage": row.language_coverage,
                "chunk_policy": row.chunk_policy,
                "extraction_revision": row.extraction_revision,
            }

    def create_retrieval_profile(self, **kwargs) -> UUID:
        with self._sessions.begin() as session:
            row = session.scalar(select(RetrievalProfileRow).where(RetrievalProfileRow.profile_key == kwargs["profile_key"]))
            if row is None:
                row = RetrievalProfileRow(**kwargs)
                session.add(row)
                session.flush()
            return row.id

    def vector_search_document_chunks(
        self,
        document_ids: list[UUID],
        *,
        profile_id: UUID | None = None,
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
                if profile_id:
                    params["profile_id"] = profile_id
                
                params.update({f"doc_{index}": doc_id for index, doc_id in enumerate(document_ids)})
                
                profile_condition = "AND p.profile_id = :profile_id" if profile_id else ""
                
                rows = session.execute(
                    text(
                        f"""
                        SELECT p.chunk_id, 1 - (p.embedding <=> CAST(:embedding AS vector)) AS score
                        FROM document_embeddings_pg p
                        JOIN document_chunks c ON c.id = p.chunk_id
                        WHERE c.document_id IN ({placeholders})
                          AND p.model_id = :model_id
                          AND p.dimensions = :dimensions
                          {profile_condition}
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
