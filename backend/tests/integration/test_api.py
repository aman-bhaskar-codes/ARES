from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ares.api.app import create_app
from ares.api.settings import Settings


def test_keyless_demo_api_end_to_end(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'api.sqlite3'}",
    )
    client = TestClient(create_app(settings))

    health = client.get("/health/ready", headers={"X-Request-ID": "test-request-123"})
    assert health.status_code == 200
    assert health.headers["X-Request-ID"] == "test-request-123"
    assert health.json()["mode"] == "demo"
    system = client.get("/api/v1/system/status")
    status = system.json()
    assert status["mode"] == "demo"
    assert status["strict_free_mode"] is True
    assert status["billable_fallback_allowed"] is False
    assert status["gemini_model"] is None
    assert status["retrieval_backend"] == "sqlite-persisted-vector-exact"
    assert status["tools"]["jev"]["metered"] is True

    conversation = client.post("/api/v1/conversations", json={"title": "Evidence demo"})
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]

    payload = {
        "conversation_id": conversation_id,
        "query": "Show me how citation evidence is kept inspectable",
        "mode": "quick",
        "source_scope": ["web"],
        "document_ids": [],
    }
    created = client.post("/api/v1/runs", json=payload, headers={"Idempotency-Key": "api-demo-1"})
    assert created.status_code == 202
    run_id = created.json()["id"]

    replay = client.post("/api/v1/runs", json=payload, headers={"Idempotency-Key": "api-demo-1"})
    assert replay.status_code == 202
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.json()["id"] == run_id

    worker = client.post("/api/v1/internal/worker/run-once")
    assert worker.status_code == 200
    assert worker.json()["processed"] is True

    final = client.get(f"/api/v1/runs/{run_id}")
    assert final.status_code == 200
    body = final.json()
    assert body["status"] == "completed"
    assert body["last_seq"] > 0
    assert body["budget_version"] == "m07-v1"
    assert body["answer_blocks"][0]["citations"]

    evidence_id = body["answer_blocks"][0]["citations"][0]["evidence_id"]
    evidence = client.get(f"/api/v1/evidence/{evidence_id}")
    assert evidence.status_code == 200
    assert evidence.json()["source"]["read_state"] == "full"

    replay_stream = client.get(f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "0"})
    assert replay_stream.status_code == 200
    assert "event: run.created" in replay_stream.text
    assert "event: answer.block" in replay_stream.text
    assert "event: run.completed" in replay_stream.text
    # M07 also emits generic copies; future additive event types remain visible to the new client.
    assert '"event_type":"run.completed"' in replay_stream.text

    after_first = client.get(f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "1"})
    assert "event: run.created" not in after_first.text
    assert "event: run.completed" in after_first.text


def test_api_capacity_returns_retryable_429_and_preserves_idempotent_replay(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'capacity.sqlite3'}",
        max_active_runs=1,
    )
    client = TestClient(create_app(settings))
    conversation = client.post("/api/v1/conversations", json={"title": "Capacity"})
    conversation_id = conversation.json()["id"]
    first_payload = {
        "conversation_id": conversation_id,
        "query": "first active run",
        "mode": "quick",
        "source_scope": ["web"],
        "document_ids": [],
    }
    first = client.post(
        "/api/v1/runs", json=first_payload, headers={"Idempotency-Key": "capacity-1"}
    )
    assert first.status_code == 202

    replay = client.post(
        "/api/v1/runs", json=first_payload, headers={"Idempotency-Key": "capacity-1"}
    )
    assert replay.status_code == 202
    assert replay.headers["X-Idempotent-Replay"] == "true"

    second_payload = {**first_payload, "query": "second active run"}
    rejected = client.post(
        "/api/v1/runs", json=second_payload, headers={"Idempotency-Key": "capacity-2"}
    )
    assert rejected.status_code == 429
    assert rejected.headers["Retry-After"] == "5"
    assert rejected.json()["detail"]["code"] == "RUN_CAPACITY_REACHED"


def test_invalid_incoming_request_id_is_replaced(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo", database_url=f"sqlite+pysqlite:///{tmp_path / 'request-id.sqlite3'}"
    )
    client = TestClient(create_app(settings))
    response = client.get("/health/live", headers={"X-Request-ID": "bad request id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad request id"
    assert len(response.headers["X-Request-ID"]) == 36


def test_security_headers_and_request_size_limit(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'headers.sqlite3'}",
        max_request_body_bytes=1024,
        max_upload_bytes=1024,
    )
    client = TestClient(create_app(settings))
    response = client.get("/api/v1/system/status")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]

    rejected = client.post(
        "/api/v1/conversations",
        content=b"x" * 2048,
        headers={"Content-Type": "application/json", "Content-Length": "2048"},
    )
    assert rejected.status_code == 413
    assert rejected.json()["detail"]["code"] == "REQUEST_TOO_LARGE"


def test_run_create_round_trips_date_window(tmp_path: Path) -> None:
    settings = Settings(
        ares_mode="demo", database_url=f"sqlite+pysqlite:///{tmp_path / 'date-window-api.sqlite3'}"
    )
    client = TestClient(create_app(settings))
    conversation = client.post("/api/v1/conversations", json={"title": "Date filter"}).json()
    response = client.post(
        "/api/v1/runs",
        headers={"Idempotency-Key": "date-window-api-1"},
        json={
            "conversation_id": conversation["id"],
            "query": "January research",
            "mode": "quick",
            "source_scope": ["web"],
            "document_ids": [],
            "date_window": {
                "start": "2026-01-01T00:00:00+05:30",
                "end": "2026-01-31T23:59:59+05:30",
                "timezone": "Asia/Kolkata",
            },
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["date_window"]["timezone"] == "Asia/Kolkata"
    assert body["date_window"]["start"].startswith("2026-01-01")
    assert body["deadline_at"] is not None
