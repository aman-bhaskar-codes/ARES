from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from ares.adapters.db import build_session_factory
from ares.application.documents import PreparedChunk
from ares.application.repository import Repository
from ares.domain.models import DocumentStatus


POSTGRES_URL = os.getenv("ARES_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="ARES_TEST_POSTGRES_URL is not configured")


def test_pgvector_exact_search_uses_migrated_sidecar() -> None:
    from ares.application.auth import AuthStore
    from ares.application.identity import principal_scope
    
    assert POSTGRES_URL is not None
    engine, sessions = build_session_factory(POSTGRES_URL)
    store = AuthStore(sessions)
    principal = store.upsert_identity(subject=f"pgvector-{uuid4()}", email=None, display_name="V")
    
    repository = Repository(sessions)
    suffix = uuid4().hex[:8]
    memory = "Agent memory evaluation requires durable evidence and retrieval measurements."
    traffic = "Traffic signal timing optimizes corridor progression and queue discharge."
    with principal_scope(principal):
        document = repository.create_user_document(
            name=f"vector-{suffix}.txt",
            mime_type="text/plain",
        text=memory + "\n\n" + traffic,
        raw_bytes=(memory + "\n\n" + traffic).encode(),
        blob_key=None,
        status=DocumentStatus.READY,
        page_count=None,
        page_map=[],
        warnings=[],
        parser_version="test",
        chunks=[
            PreparedChunk(1, memory, 0, len(memory), None, None, "passage 1"),
            PreparedChunk(
                2, traffic, len(memory) + 2, len(memory) + 2 + len(traffic), None, None, "passage 2"
            ),
        ],
    )
    chunks = repository.get_document_chunks([document.id])
    by_text = {chunk.text: chunk.id for chunk in chunks}
    model_id = f"test-vector-{suffix}"
    repository.store_chunk_embeddings(
        model_id=model_id,
        dimensions=3,
        embeddings=[
            (by_text[memory], [1.0, 1.0, 0.0]),
            (by_text[traffic], [0.0, 0.0, 1.0]),
        ],
    )

    ranked = repository.vector_search_document_chunks(
        [document.id],
        model_id=model_id,
        dimensions=3,
        query_vector=[1.0, 1.0, 0.0],
        limit=2,
    )

    assert ranked[0][0] == by_text[memory]
    assert ranked[0][1] > ranked[1][1]
    with engine.connect() as connection:
        extension = connection.scalar(
            text("SELECT extname FROM pg_extension WHERE extname='vector'")
        )
        assert extension == "vector"
    engine.dispose()
