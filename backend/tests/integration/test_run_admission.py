from pathlib import Path

import pytest

from ares.adapters.db import Base, build_session_factory
from ares.application.repository import Repository, RunAdmissionError
from ares.domain.models import RunCreate


def test_active_run_cap_allows_idempotent_replay_but_rejects_new_run(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'admission.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = Repository(sessions)
    conversation = repository.create_conversation("admission")
    payload = RunCreate(conversation_id=conversation.id, query="first active run")

    first, created = repository.create_run(payload, "admission-1", max_active_runs=1)
    assert created is True
    replay, created = repository.create_run(payload, "admission-1", max_active_runs=1)
    assert created is False
    assert replay.id == first.id

    with pytest.raises(RunAdmissionError, match="active run limit"):
        repository.create_run(
            RunCreate(conversation_id=conversation.id, query="second active run"),
            "admission-2",
            max_active_runs=1,
        )
