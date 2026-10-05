from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.api.app import create_app
from ares.api.settings import Settings
from ares.application.engine import DemoResearchEngine
from ares.application.exports import ExportService
from ares.application.repository import Repository
from ares.domain.models import DocumentStatus, FetchedDocument, RunCreate, RunMode
from ares.application.documents import PreparedChunk
from ares.domain.research import EvidenceCandidate


def test_document_identity_is_distinct_from_run_source_and_reusable(repository: Repository) -> None:
    text = "Evidence must stay inspectable across repeated research runs."
    document = repository.create_user_document(
        name="notes.md",
        mime_type="text/markdown",
        text=text,
        raw_bytes=text.encode(),
        blob_key=None,
        status=DocumentStatus.READY,
        page_count=None,
        page_map=[],
        warnings=[],
        parser_version="test",
        chunks=[PreparedChunk(1, text, 0, len(text), None, None, "passage 1")],
    )
    conversation = repository.create_conversation("reuse")
    source_ids = []
    for suffix in ("a", "b"):
        run, _ = repository.create_run(
            RunCreate(
                conversation_id=conversation.id,
                query="What must stay inspectable?",
                mode=RunMode.QUICK,
                source_scope=["documents"],
                document_ids=[document.id],
            ),
            idempotency_key=f"reuse-{suffix}",
        )
        source_id = uuid4()
        source_ids.append(source_id)
        fetched = FetchedDocument(
            source_id=source_id,
            user_document_id=document.id,
            title=document.name,
            url=f"https://local.ares.invalid/documents/{document.id}",
            final_url=f"https://local.ares.invalid/documents/{document.id}",
            text=text,
            content_hash=document.content_hash,
            extraction_method="user-document",
            mime_type=document.mime_type,
            byte_count=document.byte_count,
            source_kind="document",
            canonical_identifier=f"ares:document:{document.id}",
        )
        packets = repository.persist_document_evidence(
            run.id,
            document=fetched,
            candidates=[EvidenceCandidate(
                source_id=source_id,
                title=document.name,
                url=f"https://local.ares.invalid/documents/{document.id}",
                text=text,
                locator="passage 1",
                char_start=0,
                char_end=len(text),
                combined_score=1.0,
            )],
            provider="documents",
        )
        assert packets[0].source_id == source_id
        assert run.document_ids == [document.id]

    assert source_ids[0] != source_ids[1]


def test_demo_export_is_persisted_and_downloadable(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'export.sqlite3'}",
        blob_root=str(tmp_path / "blobs"),
    )
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post("/api/v1/conversations", json={"title": "Export"}).json()
    run = client.post(
        "/api/v1/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "conversation_id": conversation["id"],
            "query": "Explain inspectable citations",
            "mode": "quick",
            "source_scope": ["web"],
            "document_ids": [],
        },
    ).json()
    client.post("/api/v1/internal/worker/run-once")

    artifact = client.post(f"/api/v1/runs/{run['id']}/exports", json={"format": "markdown"})
    assert artifact.status_code == 201
    body = artifact.json()
    downloaded = client.get(body["download_url"])
    assert downloaded.status_code == 200
    assert "ARES research export" in downloaded.text
    assert "Content hash" in downloaded.text

    manifest = client.post(f"/api/v1/runs/{run['id']}/exports", json={"format": "json"})
    assert manifest.status_code == 201
    payload = client.get(manifest.json()["download_url"]).json()
    assert payload["schema_version"] == 1
    assert payload["run"]["id"] == run["id"]
    assert payload["evidence"]
