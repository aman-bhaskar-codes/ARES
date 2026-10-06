from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ares.application.rag import EmbeddingProvider
from ares.application.repository import IngestionLease, Repository
from ares.domain.budgets import calculate_provider_cost


@dataclass(frozen=True, slots=True)
class IndexingResult:
    document_id: UUID
    embedded_chunks: int
    semantic_ready: bool


class DocumentEmbeddingIndexer:
    """Background corpus indexer.

    M08 intentionally keeps document embedding production off the interactive
    research query path. This service is called by an ingestion/media worker once
    lexical publication has committed.
    """

    def __init__(
        self,
        repository: Repository,
        embedder: EmbeddingProvider | None,
        *,
        model_id: str,
        dimensions: int,
        batch_size: int = 32,
        max_chunks: int = 5_000,
        remote_provider: str | None = None,
        rpm: int = 1,
        tpm: int = 1,
        rpd: int = 1,
    ) -> None:
        self.repository = repository
        self.embedder = embedder
        self.model_id = model_id
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.max_chunks = max_chunks
        self.remote_provider = remote_provider
        self.rpm = rpm
        self.tpm = tpm
        self.rpd = rpd

    def index_document(self, lease: IngestionLease, document_id: UUID) -> IndexingResult:
        if self.embedder is None:
            self.repository.mark_document_semantic_ready(lease, document_id, ready=False)
            return IndexingResult(document_id=document_id, embedded_chunks=0, semantic_ready=False)

        pending = self.repository.get_missing_embedding_chunks(
            [document_id],
            model_id=self.model_id,
            dimensions=self.dimensions,
            limit=self.max_chunks + 1,
        )
        if len(pending) > self.max_chunks:
            raise RuntimeError("document exceeds configured background embedding chunk budget")

        embedded = 0
        for start in range(0, len(pending), self.batch_size):
            rows = pending[start : start + self.batch_size]
            texts = [row.text for row in rows]
            if self.remote_provider is not None:
                estimated_input_tokens = max(1, sum(max(1, len(text) // 4) for text in texts))
                cost_usd = calculate_provider_cost(self.model_id, estimated_input_tokens, 0)
                self.repository.reserve_provider_usage(
                    provider=self.remote_provider,
                    model=self.model_id,
                    rpm=self.rpm,
                    tpm=self.tpm,
                    rpd=self.rpd,
                    input_tokens=estimated_input_tokens,
                    output_tokens=0,
                    cost_usd=cost_usd,
                )
            vectors = self.embedder.embed_documents(texts)
            if len(vectors) != len(rows):
                raise RuntimeError("embedding provider returned an unexpected vector count")
            self.repository.store_chunk_embeddings(
                model_id=self.model_id,
                dimensions=self.dimensions,
                embeddings=[(row.id, vector) for row, vector in zip(rows, vectors, strict=True)],
            )
            embedded += len(rows)

        # Re-check rather than assuming this worker had the only writer. This also
        # makes retry after a partial/crashed batch idempotent.
        remaining = self.repository.get_missing_embedding_chunks(
            [document_id], model_id=self.model_id, dimensions=self.dimensions, limit=1
        )
        ready = not remaining
        self.repository.mark_document_semantic_ready(lease, document_id, ready=ready)
        return IndexingResult(
            document_id=document_id, embedded_chunks=embedded, semantic_ready=ready
        )
