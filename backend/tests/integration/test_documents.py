from __future__ import annotations

from uuid import uuid4
from fastapi.testclient import TestClient

from ares.api.app import create_app
from ares.api.settings import Settings


def test_text_document_can_be_ingested_and_referenced_by_run(tmp_path):
    db = tmp_path / "doc.sqlite3"
    app = create_app(Settings(ares_mode="demo", database_url=f"sqlite+pysqlite:///{db}"))
    client = TestClient(app)
    created = client.post("/api/v1/documents/text", json={
        "name": "notes.md", "mime_type": "text/markdown", "text": "# Finding\nARES preserves exact evidence spans."
    })
    assert created.status_code == 201
    document_id = created.json()["id"]
    conversation = client.post("/api/v1/conversations", json={"title": "Docs"}).json()
    run = client.post(
        "/api/v1/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "conversation_id": conversation["id"], "query": "What does the note say about evidence?",
            "mode": "quick", "source_scope": ["documents"], "document_ids": [document_id],
        },
    )
    assert run.status_code == 202
