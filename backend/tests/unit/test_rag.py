from __future__ import annotations

from uuid import uuid4

from ares.application.rag import HybridRAGRetriever, RAGConfig
from ares.domain.models import FetchedDocument


def _doc(title: str, text: str, url: str) -> FetchedDocument:
    return FetchedDocument(
        source_id=uuid4(),
        title=title,
        url=url,
        final_url=url,
        text=text,
        content_hash=(title.encode().hex() + "0" * 64)[:64],
        extraction_method="fixture",
        mime_type="text/plain",
        byte_count=len(text.encode()),
    )


def test_rag_selects_relevant_exact_passage_and_preserves_offsets() -> None:
    irrelevant = ("Gardening soil and irrigation practices. " * 30).strip()
    relevant = (
        "Agent memory systems are commonly evaluated using retrieval accuracy and downstream task success. "
        "A major limitation is that benchmarks often mix memory quality with planner quality. " * 12
    ).strip()
    docs = [
        _doc("Garden", irrelevant, "https://example.com/garden"),
        _doc("Memory", relevant, "https://example.com/memory"),
    ]
    retriever = HybridRAGRetriever(config=RAGConfig(target_chars=650, min_chunk_chars=120))
    result = retriever.retrieve("agent memory evaluation limitations", docs, limit=3)

    assert result
    assert result[0].source_id == docs[1].source_id
    for candidate in result:
        source = next(doc for doc in docs if doc.source_id == candidate.source_id)
        assert (
            source.text[candidate.char_start : candidate.char_end].strip() == candidate.text.strip()
        )


def test_rag_enforces_source_diversity() -> None:
    repeated = ("ARES evidence provenance citation retrieval research system. " * 80).strip()
    docs = [
        _doc("A", repeated, "https://a.example/x"),
        _doc("B", repeated, "https://b.example/x"),
    ]
    retriever = HybridRAGRetriever(
        config=RAGConfig(target_chars=500, min_chunk_chars=100, max_chunks_per_source=1)
    )
    result = retriever.retrieve("evidence provenance citation", docs, limit=4)
    assert len({candidate.source_id for candidate in result}) == 2
    assert len(result) == 2


def test_semantic_and_lexical_retrievers_fuse_by_rank_not_raw_scale():
    class FakeEmbedder:
        def embed_query(self, text):
            return [1.0, 0.0]

        def embed_documents(self, texts):
            # Make the second candidate semantically strongest with a very different raw scale.
            return [[0.0, 1.0], [1.0, 0.0]]

    from ares.application.rag import HybridRAGRetriever, RAGConfig
    from ares.domain.models import FetchedDocument
    from datetime import UTC, datetime
    from uuid import uuid4

    docs = [
        FetchedDocument(
            source_id=uuid4(),
            title="Lexical",
            url="https://a.example/x",
            final_url="https://a.example/x",
            text=("alpha query term " * 40) + (" filler" * 80),
            content_hash="a" * 64,
            fetched_at=datetime.now(UTC),
            extraction_method="test",
            byte_count=1000,
        ),
        FetchedDocument(
            source_id=uuid4(),
            title="Semantic",
            url="https://b.example/x",
            final_url="https://b.example/x",
            text=("conceptually relevant material " * 50),
            content_hash="b" * 64,
            fetched_at=datetime.now(UTC),
            extraction_method="test",
            byte_count=1000,
        ),
    ]
    retriever = HybridRAGRetriever(
        config=RAGConfig(target_chars=500, min_chunk_chars=100), embedder=FakeEmbedder()
    )
    results = retriever.retrieve("alpha query term", docs, limit=4)
    assert results
    assert any(item.semantic_score is not None for item in results)
    assert all(0.0 <= item.combined_score <= 1.0 for item in results)


def test_retrieval_trace_exposes_ablation_ranks_without_changing_retrieve_contract() -> None:
    from ares.application.rag import RAGConfig

    docs = [
        _doc(
            "Alpha",
            "Vector databases use nearest-neighbor search for semantic retrieval. " * 8,
            "https://alpha.example",
        ),
        _doc(
            "Beta",
            "PostgreSQL transactions use MVCC for concurrent workloads. " * 8,
            "https://beta.example",
        ),
    ]
    retriever = HybridRAGRetriever(
        config=RAGConfig(mode="lexical", min_chunk_chars=20, target_chars=300)
    )
    result = retriever.retrieve_with_trace("semantic nearest neighbor retrieval", docs, limit=2)
    assert result.mode == "lexical"
    assert result.semantic_used is False
    assert result.candidates[0].title == "Alpha"
    assert len(result.trace) >= 2
    assert min(item.lexical_rank for item in result.trace) == 1
