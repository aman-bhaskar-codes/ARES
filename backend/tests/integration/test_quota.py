from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from ares.application.repository import QuotaExceededError, Repository


def test_provider_request_quota_is_atomic_and_fail_closed(repository: Repository) -> None:
    repository.reserve_provider_usage(
        provider="gemini", model="gemini-3.8-flash", rpm=1, tpm=1000, rpd=10, input_tokens=100, output_tokens=0, cost_usd=0.0
    )
    with pytest.raises(QuotaExceededError, match="requests-per-minute"):
        repository.reserve_provider_usage(
            provider="gemini", model="gemini-3.8-flash", rpm=1, tpm=1000, rpd=10, input_tokens=100, output_tokens=0, cost_usd=0.0
        )


def test_provider_token_quota_fails_before_call(repository: Repository) -> None:
    with pytest.raises(QuotaExceededError, match="input-token"):
        repository.reserve_provider_usage(
            provider="gemini", model="gemini-3.8-flash", rpm=10, tpm=50, rpd=10, input_tokens=100, output_tokens=0, cost_usd=0.0
        )


def test_simultaneous_quota_reservations_admit_exactly_one(repository: Repository) -> None:
    barrier = Barrier(2)

    def reserve() -> str:
        barrier.wait(timeout=5)
        try:
            repository.reserve_provider_usage(
                provider="gemini",
                model="concurrency-test",
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
        outcomes = sorted(f.result(timeout=10) for f in futures)

    assert outcomes == ["admitted", "rejected"]
