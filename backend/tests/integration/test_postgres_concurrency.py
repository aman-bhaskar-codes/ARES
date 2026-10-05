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
    from ares.adapters.db import Base
    from ares.application.repository import RunAdmissionError
    from ares.domain.models import RunCreate

    assert POSTGRES_URL is not None
    engine, sessions = build_session_factory(POSTGRES_URL)
    Base.metadata.create_all(engine)
    repository = Repository(sessions)
    conversation = repository.create_conversation(f"admission-{uuid4()}")
    barrier = Barrier(2)

    def create(index: int) -> str:
        barrier.wait(timeout=10)
        try:
            repository.create_run(
                RunCreate(conversation_id=conversation.id, query=f"concurrent run {index}"),
                f"pg-admission-{uuid4()}",
                max_active_runs=1,
            )
        except RunAdmissionError:
            return "rejected"
        return "admitted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create, i) for i in range(2)]
        outcomes = sorted(future.result(timeout=15) for future in futures)

    engine.dispose()
    assert outcomes == ["admitted", "rejected"]
