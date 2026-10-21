from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from ares.adapters.db import build_session_factory
from ares.application.repository import QuotaExceededError, Repository

POSTGRES_URL = os.getenv("ARES_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="ARES_TEST_POSTGRES_URL is not configured")


def test_postgres_serializes_provider_quota_reservations() -> None:
    assert POSTGRES_URL is not None
    engine, sessions = build_session_factory(POSTGRES_URL)
    repository = Repository(sessions)
    model = f"quota-{uuid4()}"
    barrier = Barrier(2)

    def reserve() -> str:
        barrier.wait(timeout=10)
        try:
            repository.reserve_provider_usage(
                provider="gemini",
                model=model,
                rpm=1,
                tpm=1000,
                rpd=10,
                input_tokens=100,
                output_tokens=0,
                cost_usd=0.0,
            )
        except QuotaExceededError:
            return "rejected"
        return "admitted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve) for _ in range(2)]
        outcomes = sorted(f.result(timeout=15) for f in futures)

    engine.dispose()
    assert outcomes == ["admitted", "rejected"]


def test_postgres_serializes_active_run_admission() -> None:
    from ares.adapters.db import Base, RunRow
    from ares.application.auth import AuthStore
    from ares.application.identity import principal_scope
    from ares.application.repository import RunAdmissionError
    from ares.domain.models import RunCreate, RunStatus
    from sqlalchemy import func, select

    assert POSTGRES_URL is not None
    engine, sessions = build_session_factory(POSTGRES_URL)
    Base.metadata.create_all(engine)
    
    store = AuthStore(sessions)
    principal = store.upsert_identity(subject=f"concurrency-{uuid4()}", email=None, display_name="C")
        
    repository = Repository(sessions)
    with principal_scope(principal):
        conversation = repository.create_conversation(f"admission-{uuid4()}")
        barrier = Barrier(2)
    # Other fixture workspaces can retain queued runs; reserve exactly one additional global slot.
    with sessions() as session:
        active_statuses = [status.value for status in RunStatus if not status.terminal]
        existing_active = session.scalar(select(func.count(RunRow.id)).where(RunRow.status.in_(active_statuses))) or 0

    def create(index: int) -> str:
        barrier.wait(timeout=10)
        try:
            with principal_scope(principal):
                repository.create_run(
                    RunCreate(conversation_id=conversation.id, query=f"concurrent run {index}"),
                    f"pg-admission-{uuid4()}",
                    max_active_runs=existing_active + 1,
                )
        except RunAdmissionError:
            return "rejected"
        return "admitted"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create, i) for i in range(2)]
            outcomes = sorted(future.result(timeout=15) for future in futures)
        assert outcomes == ["admitted", "rejected"]
    finally:
        with principal_scope(principal):
            repository.delete_conversation(conversation.id)
        engine.dispose()
