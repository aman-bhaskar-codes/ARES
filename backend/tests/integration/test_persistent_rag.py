from __future__ import annotations

from ares.application.documents import PreparedChunk
from ares.application.persistent_rag import PersistentDocumentRAG
from ares.domain.models import DocumentStatus


class FakeEmbedder:
    def __init__(self):
        self.document_calls = 0
        self.query_calls = 0

    @staticmethod
    def _vector(text: str) -> list[float]:
        lower = text.casefold()
        return [
            1.0 if "memory" in lower else 0.1,
            1.0 if "evaluation" in lower else 0.1,
            1.0 if "traffic" in lower else 0.1,
        ]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return self._vector(text)


def test_query_path_does_not_create_corpus_embeddings(repository) -> None:
    first_text = "Memory evaluation compares retrieval quality and long-term agent behavior."
    second_text = "Traffic signal timing is unrelated to agent memory research."
    document = repository.create_user_document(
        name="paper.txt",
        mime_type="text/plain",
        text=first_text + "\n\n" + second_text,
        raw_bytes=(first_text + "\n\n" + second_text).encode(),
        blob_key=None,
        status=DocumentStatus.READY,
        page_count=None,
        page_map=[],
        warnings=[],
        parser_version="test",
        chunks=[
            PreparedChunk(1, first_text, 0, len(first_text), None, None, "passage 1"),
            PreparedChunk(
                2, second_text, len(first_text) + 2,
                len(first_text) + 2 + len(second_text), None, None, "passage 2"
            ),
        ],
    )
    rows = repository.get_documents([document.id])
    embedder = FakeEmbedder()
    rag = PersistentDocumentRAG(
        repository, embedder=embedder, model_id="fake-3d", dimensions=3,
        rpm=100, tpm=100_000, rpd=1000,
    )
    source_map = {document.id: __import__("uuid").uuid4()}

    first = rag.retrieve("agent memory evaluation", documents=rows, source_id_by_document=source_map, limit=2)
    second = rag.retrieve("agent memory evaluation", documents=rows, source_id_by_document=source_map, limit=2)

    assert first.semantic_used is False
    assert second.semantic_used is False
    assert first.embedded_chunks == 0
    assert second.embedded_chunks == 0
    assert embedder.document_calls == 0
    assert embedder.query_calls == 0
    assert first.candidates[0].text == first_text
