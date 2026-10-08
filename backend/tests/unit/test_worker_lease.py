from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ares.application.repository import JobLease, StaleLeaseError
from ares.worker.main import LeaseKeepAlive


def _lease() -> JobLease:
    return JobLease(
        run_id=uuid4(),
        token=uuid4(),
        leased_until=datetime.now(UTC) + timedelta(seconds=30),
        attempt=1,
    )


class TransientHeartbeatRepository:
    def __init__(self) -> None:
        self.calls = 0

    def heartbeat(self, lease: JobLease) -> JobLease:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary database interruption")
        return JobLease(
            run_id=lease.run_id,
            token=lease.token,
            leased_until=datetime.now(UTC) + timedelta(seconds=30),
            attempt=lease.attempt,
        )


class StaleHeartbeatRepository:
    def __init__(self) -> None:
        self.calls = 0

    def heartbeat(self, lease: JobLease) -> JobLease:
        self.calls += 1
        raise StaleLeaseError("lease fenced")


def test_keepalive_retries_transient_heartbeat_failure() -> None:
    repository = TransientHeartbeatRepository()
    with LeaseKeepAlive(repository, _lease(), interval_seconds=0.02) as keepalive:
        deadline = time.monotonic() + 0.5
        while repository.calls < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    assert repository.calls >= 2
    assert keepalive.lease_lost is False


def test_keepalive_marks_stale_lease_as_lost() -> None:
    repository = StaleHeartbeatRepository()
    with LeaseKeepAlive(repository, _lease(), interval_seconds=0.01) as keepalive:
        deadline = time.monotonic() + 0.5
        while not keepalive.lease_lost and time.monotonic() < deadline:
            time.sleep(0.01)
    assert repository.calls >= 1
    assert keepalive.lease_lost is True


class PresenceRepository:
    def __init__(self) -> None:
        self.worker_id = uuid4()
        self.heartbeats: list[dict[str, object]] = []

    def register_worker(self, instance_name: str, *, capabilities=None):
        self.registered = dict(capabilities or {})
        return self.worker_id

    def heartbeat_worker(self, worker_id, *, state="active", capabilities=None) -> None:
        self.heartbeats.append({"state": state, **dict(capabilities or {})})

    def stop_worker(self, worker_id) -> None:
        pass


def test_worker_presence_refreshes_capabilities_on_heartbeat(tmp_path) -> None:
    from ares.worker.main import WorkerPresence

    repository = PresenceRepository()
    states = iter([{"audio": False}, {"audio": True}, {"audio": True}])
    presence = WorkerPresence(
        repository,  # type: ignore[arg-type]
        interval_seconds=0.01,
        health_file=str(tmp_path / "worker.health"),
        profile="media",
        capabilities={"audio": False},
        capabilities_provider=lambda: next(states, {"audio": True}),
    )
    presence.start()
    try:
        deadline = time.monotonic() + 0.5
        while (
            not any(item.get("audio") is True for item in repository.heartbeats)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
    finally:
        presence.close()

    assert repository.registered == {"audio": False}
    assert any(item.get("audio") is True for item in repository.heartbeats)
