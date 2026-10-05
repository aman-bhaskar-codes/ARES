from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from ares.adapters.db import Base, JobRow, build_session_factory
from ares.application.repository import Repository
from ares.domain.models import RunCreate, RunStatus


def test_expired_worker_leases_fail_closed_after_retry_budget(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'retry.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = Repository(sessions)
    conversation = repository.create_conversation("retry")
    run, _ = repository.create_run(RunCreate(conversation_id=conversation.id, query="retry me"), "retry-1")

    first = repository.claim_next_job(max_attempts=2)
    assert first is not None and first.attempt == 1
    with sessions.begin() as session:
        row = session.scalar(select(JobRow).where(JobRow.run_id == run.id))
        assert row is not None
        row.leased_until = datetime.now(UTC) - timedelta(seconds=1)

    second = repository.claim_next_job(max_attempts=2)
    assert second is not None and second.attempt == 2
    with sessions.begin() as session:
        row = session.scalar(select(JobRow).where(JobRow.run_id == run.id))
        assert row is not None
        row.leased_until = datetime.now(UTC) - timedelta(seconds=1)

    assert repository.claim_next_job(max_attempts=2) is None
    snapshot = repository.get_run(run.id)
    assert snapshot.status is RunStatus.FAILED
    assert snapshot.error_code == "WORKER_RETRY_EXHAUSTED"
