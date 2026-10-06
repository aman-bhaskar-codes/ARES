from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from ares.adapters.db import Base, JobRow, WorkspaceMembershipRow, build_session_factory
from ares.application.repository import (
    Repository,
    ResourceCapacityError,
    RunAuthorizationError,
    RunBudgetExceededError,
    StaleLeaseError,
)
from ares.application.run_context import RunContext, RunDeadlineExceeded
from ares.domain.budgets import BUDGETS
from ares.domain.models import DateWindow, RunCreate, RunMode


def repository_for(tmp_path: Path) -> tuple[Repository, object]:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'm07.sqlite3'}")
    Base.metadata.create_all(engine)
    return Repository(sessions), sessions


def create_leased_run(repository: Repository, *, key: str = "m07-run"):
    conversation = repository.create_conversation("M07 execution")
    run, _ = repository.create_run(
        RunCreate(
            conversation_id=conversation.id,
            query="verify the execution contract",
            mode=RunMode.QUICK,
        ),
        idempotency_key=key,
    )
    lease = repository.claim_next_job(lease_seconds=30)
    assert lease is not None
    return run, lease


def test_run_admission_persists_date_window_deadline_budget_and_cursor(tmp_path: Path) -> None:
    repository, _ = repository_for(tmp_path)
    conversation = repository.create_conversation("Date window")
    window = DateWindow(
        start=datetime(2026, 1, 1), end=datetime(2026, 1, 31, 23, 59), timezone="Asia/Kolkata"
    )
    before = datetime.now(UTC)
    run, created = repository.create_run(
        RunCreate(
            conversation_id=conversation.id,
            query="research January evidence",
            mode=RunMode.QUICK,
            date_window=window,
        ),
        idempotency_key="m07-date-window",
    )
    assert created is True
    assert run.date_window is not None
    assert run.date_window.timezone == "Asia/Kolkata"
    assert run.date_window.start is not None and run.date_window.start.tzinfo is not None
    assert run.deadline_at is not None and run.deadline_at > before
    assert run.budget_version == "m07-v1"
    assert run.usage_ledger == {}
    assert run.last_seq == 1


def test_persisted_usage_ledger_enforces_limit_atomically(tmp_path: Path) -> None:
    repository, _ = repository_for(tmp_path)
    run, lease = create_leased_run(repository, key="m07-budget")
    assert (
        repository.consume_run_usage(
            run.id, delta={"llm_calls": 1}, limits={"llm_calls": 1}, lease_token=lease.token
        )["llm_calls"]
        == 1
    )
    with pytest.raises(RunBudgetExceededError):
        repository.consume_run_usage(
            run.id, delta={"llm_calls": 1}, limits={"llm_calls": 1}, lease_token=lease.token
        )
    assert repository.get_run(run.id).usage_ledger["llm_calls"] == 1


def test_completed_checkpoint_restores_after_worker_reclaim_and_stale_lease_cannot_write(
    tmp_path: Path,
) -> None:
    repository, sessions = repository_for(tmp_path)
    run, first = create_leased_run(repository, key="m07-checkpoint")
    assert (
        repository.start_checkpoint(
            run.id, step_key="synthesis.final", input_hash="a" * 64, lease_token=first.token
        )
        is None
    )
    repository.complete_checkpoint(
        run.id,
        step_key="synthesis.final",
        input_hash="a" * 64,
        output={"answer": "persisted"},
        lease_token=first.token,
    )

    # Simulate a worker dying after durable publication but before finishing its job.
    with sessions.begin() as session:
        job = session.scalar(select(JobRow).where(JobRow.run_id == run.id))
        assert job is not None
        job.leased_until = datetime.now(UTC) - timedelta(seconds=1)

    second = repository.claim_next_job(lease_seconds=30)
    assert second is not None and second.run_id == run.id and second.token != first.token
    restored = repository.start_checkpoint(
        run.id, step_key="synthesis.final", input_hash="a" * 64, lease_token=second.token
    )
    assert restored == {"answer": "persisted"}

    with pytest.raises(StaleLeaseError):
        repository.complete_checkpoint(
            run.id,
            step_key="synthesis.final",
            input_hash="a" * 64,
            output={"answer": "stale overwrite"},
            lease_token=first.token,
        )


def test_resource_slot_capacity_is_fleet_visible_and_releasable(tmp_path: Path) -> None:
    repository, _ = repository_for(tmp_path)
    run, lease = create_leased_run(repository, key="m07-resource")
    held = repository.acquire_resource_lease(
        run.id, resource_key="provider:fixture", capacity=1, ttl_seconds=20, lease_token=lease.token
    )
    with pytest.raises(ResourceCapacityError):
        repository.acquire_resource_lease(
            run.id,
            resource_key="provider:fixture",
            capacity=1,
            ttl_seconds=20,
            lease_token=lease.token,
        )
    repository.release_resource_lease(held)
    replacement = repository.acquire_resource_lease(
        run.id, resource_key="provider:fixture", capacity=1, ttl_seconds=20, lease_token=lease.token
    )
    assert replacement.slot == 0


def test_worker_execution_reauthorizes_workspace_membership(tmp_path: Path) -> None:
    repository, sessions = repository_for(tmp_path)
    run, lease = create_leased_run(repository, key="m07-authz")
    repository.authorize_run_execution(run.id, lease_token=lease.token)
    with sessions.begin() as session:
        session.execute(delete(WorkspaceMembershipRow))
    with pytest.raises(RunAuthorizationError):
        repository.authorize_run_execution(run.id, lease_token=lease.token)


def test_run_context_rejects_expired_persisted_deadline(tmp_path: Path) -> None:
    repository, _ = repository_for(tmp_path)
    run, lease = create_leased_run(repository, key="m07-expired-deadline")
    expired = run.model_copy(update={"deadline_at": datetime.now(UTC) - timedelta(seconds=1)})
    context = RunContext(
        repository=repository, lease=lease, run=expired, budget=BUDGETS[RunMode.QUICK]
    )
    with pytest.raises(RunDeadlineExceeded):
        context.check()
