from __future__ import annotations

from pathlib import Path

import pytest

from ares.adapters.db import Base, build_session_factory
from ares.application.auth import AuthStore
from ares.application.identity import principal_scope
from ares.application.repository import NotFoundError, Repository, RunAdmissionError
from ares.domain.models import DocumentStatus, RunCreate


def _stack(tmp_path: Path):
    engine, sessions = build_session_factory(
        f"sqlite+pysqlite:///{tmp_path / 'm6-admission.sqlite3'}"
    )
    Base.metadata.create_all(engine)
    return AuthStore(sessions), Repository(sessions)


def test_per_user_workspace_and_scoped_idempotency(tmp_path: Path) -> None:
    store, repo = _stack(tmp_path)
    a = store.upsert_identity(subject="i|a", email=None, display_name="A")
    b = store.upsert_identity(subject="i|b", email=None, display_name="B")
    with principal_scope(a):
        ca = repo.create_conversation("A")
        first, created = repo.create_run(
            RunCreate(conversation_id=ca.id, query="one"),
            "same-client-key",
            max_active_runs=10,
            max_active_runs_per_workspace=2,
            max_active_runs_per_user=1,
        )
        assert created
        replay, created = repo.create_run(
            RunCreate(conversation_id=ca.id, query="one"),
            "same-client-key",
            max_active_runs=10,
            max_active_runs_per_workspace=2,
            max_active_runs_per_user=1,
        )
        assert not created and replay.id == first.id
        with pytest.raises(RunAdmissionError, match="user active run limit"):
            repo.create_run(
                RunCreate(conversation_id=ca.id, query="two"),
                "a-second",
                max_active_runs=10,
                max_active_runs_per_workspace=2,
                max_active_runs_per_user=1,
            )

    with principal_scope(b):
        cb = repo.create_conversation("B")
        # Same browser idempotency key is safe in another workspace because the stored key is scoped.
        _, created = repo.create_run(
            RunCreate(conversation_id=cb.id, query="one"),
            "same-client-key",
            max_active_runs=10,
            max_active_runs_per_workspace=2,
            max_active_runs_per_user=1,
        )
        assert created


def test_run_cannot_reference_another_workspace_document(tmp_path: Path) -> None:
    store, repo = _stack(tmp_path)
    a = store.upsert_identity(subject="i|a-doc", email=None, display_name="A")
    b = store.upsert_identity(subject="i|b-doc", email=None, display_name="B")
    with principal_scope(a):
        document = repo.create_user_document(
            name="private.txt",
            mime_type="text/plain",
            text="private",
            raw_bytes=b"private",
            blob_key=None,
            status=DocumentStatus.READY,
            page_count=None,
            page_map=[],
            warnings=[],
            parser_version="test",
            chunks=[],
        )
    with principal_scope(b):
        conversation = repo.create_conversation("B")
        with pytest.raises(NotFoundError, match="document not found"):
            repo.create_run(
                RunCreate(
                    conversation_id=conversation.id,
                    query="steal document",
                    source_scope=["documents"],
                    document_ids=[document.id],
                ),
                "cross-doc",
            )
