from __future__ import annotations

from uuid import uuid4

from ares.application.rag import HybridRAGRetriever, RAGConfig
from ares.domain.models import FetchedDocument, RunCreate


def test_persisted_evidence_is_anchored_to_immutable_document_version(repository) -> None:
    conversation = repository.create_conversation("Provenance")
    run, _ = repository.create_run(
        RunCreate(conversation_id=conversation.id, query="ARES citation evidence"),
        idempotency_key="provenance-1",
    )
    lease = repository.claim_next_job()
    assert lease is not None

    text = (
        "ARES stores immutable document versions so citations remain inspectable. "
        "Evidence passages carry exact source offsets and are linked to a fetched version. " * 8
    ).strip()
    document = FetchedDocument(
        source_id=uuid4(),
        title="Provenance fixture",
        url="https://example.com/original?utm_source=test",
        final_url="https://example.com/original",
        text=text,
        content_hash="a" * 64,
        extraction_method="fixture",
        mime_type="text/plain",
        byte_count=len(text.encode()),
    )
    candidates = HybridRAGRetriever(
        config=RAGConfig(target_chars=500, min_chunk_chars=100)
    ).retrieve("immutable citation source offsets", [document], limit=2)
    packets = repository.persist_document_evidence(
        run.id,
        document=document,
        candidates=candidates,
        provider="fixture",
        discovery_rank=1,
        snippet="fixture snippet",
        lease_token=lease.token,
    )

    assert packets
    evidence = repository.get_evidence(packets[0].evidence_id)
    assert evidence.document_version_id is not None
    assert evidence.char_start is not None and evidence.char_end is not None
    assert text[evidence.char_start : evidence.char_end].strip() == evidence.text.strip()
    assert evidence.source.provider == "fixture"
    assert evidence.source.discovery_rank == 1
