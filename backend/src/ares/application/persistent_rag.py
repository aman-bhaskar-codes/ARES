from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from ares.application.repository import QuotaExceededError, Repository
from ares.domain.research import EvidenceCandidate
from ares.application.rag import EmbeddingProvider


@dataclass(frozen=True, slots=True)
class PersistentRAGResult:
    candidates: list[EvidenceCandidate]
    semantic_used: bool
    embedded_chunks: int
    degraded_reason: str | None = None


class PersistentDocumentRAG:
    """Hybrid retrieval over persisted user-document chunks.

    M08 deliberately removes corpus embedding production from the research query path.
    PostgreSQL lexical retrieval is bounded by its full-text index; SQLite retains a
    deterministic bounded-test fallback. Query embeddings may still be generated when a
    configured semantic index is already ready for at least one selected document.
    """

    def __init__(
        self,
        repository: Repository,
        *,
        embedder: EmbeddingProvider | None = None,
        model_id: str = "",
        dimensions: int = 768,
        rpm: int = 1,
        tpm: int = 1,
        rpd: int = 1,
        reciprocal_rank_k: int = 60,
        max_chunks_per_document: int = 4,
    ):
        self.repository = repository
        self.embedder = embedder
        self.model_id = model_id
        self.dimensions = dimensions
        self.rpm = rpm
        self.tpm = tpm
        self.rpd = rpd
        self.reciprocal_rank_k = reciprocal_rank_k
        self.max_chunks_per_document = max_chunks_per_document

    def retrieve(
        self,
        query: str,
        *,
        documents: list,
        source_id_by_document: dict[UUID, UUID],
        limit: int,
    ) -> PersistentRAGResult:
        document_ids = [row.id for row in documents]
        lexical_pairs = self.repository.lexical_search_document_chunks(
            document_ids, query=query, limit=max(30, limit * 3)
        )
        lexical_order = [row for row, _score in lexical_pairs]
        lexical_scores = {row.id: score for row, score in lexical_pairs}

        semantic_scores: dict[UUID, float] = {}
        semantic_used = False
        degraded_reason: str | None = None
        semantic_document_ids = [row.id for row in documents if bool(getattr(row, "semantic_ready", False))]
        if self.embedder is not None and semantic_document_ids:
            try:
                # Legacy Gemini query embeddings remain quota-accounted. Local ONNX/FastEmbed
                # query embeddings do not consume a remote provider quota.
                if self.model_id.startswith("gemini"):
                    estimated_query_tokens = max(1, len(query) // 4)
                    self.repository.reserve_provider_usage(
                        provider="gemini-embeddings",
                        model=self.model_id,
                        rpm=self.rpm,
                        tpm=self.tpm,
                        rpd=self.rpd,
                        input_tokens=estimated_query_tokens,
                    )
                query_vector = self.embedder.embed_query(query)
                semantic = self.repository.vector_search_document_chunks(
                    semantic_document_ids,
                    model_id=self.model_id,
                    dimensions=self.dimensions,
                    query_vector=query_vector,
                    limit=max(30, limit * 3),
                )
                semantic_scores = {chunk_id: score for chunk_id, score in semantic}
                semantic_used = bool(semantic_scores)
            except QuotaExceededError:
                degraded_reason = "embedding quota exhausted; indexed lexical document retrieval used"
            except Exception as exc:
                degraded_reason = (
                    f"semantic document retrieval unavailable ({type(exc).__name__}); "
                    "indexed lexical retrieval used"
                )

        lexical_rank = {row.id: rank for rank, row in enumerate(lexical_order, start=1)}
        semantic_order = sorted(semantic_scores, key=semantic_scores.get, reverse=True)
        semantic_rank = {chunk_id: rank for rank, chunk_id in enumerate(semantic_order, start=1)}
        candidate_ids = list(dict.fromkeys([row.id for row in lexical_order] + semantic_order))
        if not candidate_ids:
            reason = degraded_reason or "selected documents have no matching searchable chunks"
            return PersistentRAGResult([], False, 0, reason)

        rows = self.repository.get_document_chunks_by_ids(candidate_ids)
        chunk_by_id = {row.id: row for row in rows}
        document_by_id = {row.id: row for row in documents}
        k = self.reciprocal_rank_k
        fused: list[tuple[UUID, float]] = []
        for chunk_id in candidate_ids:
            score = 0.0
            if chunk_id in lexical_rank:
                score += 0.65 / (k + lexical_rank[chunk_id])
            if chunk_id in semantic_rank:
                score += 0.35 / (k + semantic_rank[chunk_id])
            fused.append((chunk_id, score))
        fused.sort(key=lambda item: item[1], reverse=True)

        selected: list[EvidenceCandidate] = []
        per_document: defaultdict[UUID, int] = defaultdict(int)
        for chunk_id, score in fused:
            row = chunk_by_id.get(chunk_id)
            if row is None or per_document[row.document_id] >= self.max_chunks_per_document:
                continue
            document = document_by_id.get(row.document_id)
            source_id = source_id_by_document.get(row.document_id)
            if document is None or source_id is None:
                continue
            selected.append(
                EvidenceCandidate(
                    source_id=source_id,
                    title=document.name,
                    url=f"https://ares.local/documents/{document.id}",
                    text=row.text,
                    locator=row.locator,
                    char_start=row.char_start,
                    char_end=row.char_end,
                    page_start=row.page_start,
                    page_end=row.page_end,
                    segment_id=row.evidence_segment_id,
                    lexical_score=lexical_scores.get(row.id, 0.0),
                    semantic_score=semantic_scores.get(row.id) if semantic_used else None,
                    combined_score=score,
                )
            )
            per_document[row.document_id] += 1
            if len(selected) >= limit:
                break
        return PersistentRAGResult(selected, semantic_used, 0, degraded_reason)
