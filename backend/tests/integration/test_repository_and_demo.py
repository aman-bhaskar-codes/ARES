from __future__ import annotations


import pytest

from ares.application.engine import DemoResearchEngine
from ares.application.repository import IdempotencyConflictError, Repository, StaleLeaseError
from ares.domain.models import RunCreate, RunMode, RunStatus


def create_run(repository: Repository, *, query: str = "How does ARES keep citations inspectable?"):
    conversation = repository.create_conversation("Demo")
    request = RunCreate(conversation_id=conversation.id, query=query, mode=RunMode.QUICK)
    run, created = repository.create_run(request, idempotency_key="idem-1")
    assert created
    return conversation, request, run


def test_idempotent_create_and_conflict(repository: Repository) -> None:
    conversation, request, run = create_run(repository)
    replay, created = repository.create_run(request, idempotency_key="idem-1")
    assert not created
    assert replay.id == run.id

    changed = RunCreate(conversation_id=conversation.id, query="different", mode=RunMode.QUICK)
    with pytest.raises(IdempotencyConflictError):
        repository.create_run(changed, idempotency_key="idem-1")


def test_demo_vertical_slice_persists_answer_events_and_evidence(repository: Repository) -> None:
    _, _, run = create_run(repository)
    lease = repository.claim_next_job()
    assert lease is not None and lease.run_id == run.id

    DemoResearchEngine(repository).execute(lease)
    repository.finish_job(lease)

    snapshot = repository.get_run(run.id)
    assert snapshot.status is RunStatus.COMPLETED
    assert len(snapshot.answer_blocks) == 1
    assert len(snapshot.answer_blocks[0].citations) == 2
    assert len(snapshot.answer_blocks[0].claims) == 2
    assert snapshot.answer_blocks[0].claims[0].citation_labels == [1]

    evidence = repository.get_evidence(snapshot.answer_blocks[0].citations[0].evidence_id)
    assert evidence.source.extraction_method == "recorded-demo"
    assert evidence.support_status.value == "supported"

    events = repository.list_events(run.id)
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert any(event.event_type == "answer.block" for event in events)
    assert events[-1].event_type == "run.completed"


def test_cancellation_stops_demo_before_research_work(repository: Repository) -> None:
    _, _, run = create_run(repository)
    repository.request_cancel(run.id)
    lease = repository.claim_next_job()
    assert lease is not None
    DemoResearchEngine(repository).execute(lease)
    repository.finish_job(lease)
    assert repository.get_run(run.id).status is RunStatus.CANCELLED


def test_stale_lease_cannot_checkpoint(repository: Repository) -> None:
    _, _, run = create_run(repository)
    lease = repository.claim_next_job()
    assert lease is not None
    repository.finish_job(lease)
    with pytest.raises(StaleLeaseError):
        repository.set_status(run.id, RunStatus.PLANNING, lease_token=lease.token)


def test_m07_run_contract_persists_deadline_budget_and_last_sequence(
    repository: Repository,
) -> None:
    _, _, run = create_run(repository)
    assert run.deadline_at is not None
    assert run.budget_version == "m07-v1"
    assert run.last_seq == 1
    assert run.usage_ledger == {}


def test_checkpoint_is_idempotent_and_stale_worker_cannot_publish(repository: Repository) -> None:
    _, _, run = create_run(repository)
    lease = repository.claim_next_job()
    assert lease is not None
    assert (
        repository.start_checkpoint(
            run.id,
            step_key="fixture",
            input_hash="a" * 64,
            schema_version=1,
            lease_token=lease.token,
        )
        is None
    )
    repository.complete_checkpoint(
        run.id,
        step_key="fixture",
        input_hash="a" * 64,
        schema_version=1,
        output={"value": 1},
        lease_token=lease.token,
    )
    assert repository.start_checkpoint(
        run.id, step_key="fixture", input_hash="a" * 64, schema_version=1, lease_token=lease.token
    ) == {"value": 1}
    repository.finish_job(lease)
    with pytest.raises(StaleLeaseError):
        repository.complete_checkpoint(
            run.id,
            step_key="fixture",
            input_hash="a" * 64,
            schema_version=1,
            output={"value": 2},
            lease_token=lease.token,
        )


def test_resource_lease_capacity_is_shared_and_released(repository: Repository) -> None:
    _, _, run = create_run(repository)
    lease = repository.claim_next_job()
    assert lease is not None
    resource = repository.acquire_resource_lease(
        run.id, resource_key="provider:test", capacity=1, ttl_seconds=30, lease_token=lease.token
    )
    from ares.application.repository import ResourceCapacityError

    with pytest.raises(ResourceCapacityError):
        repository.acquire_resource_lease(
            run.id,
            resource_key="provider:test",
            capacity=1,
            ttl_seconds=30,
            lease_token=lease.token,
        )
    repository.release_resource_lease(resource)
    second = repository.acquire_resource_lease(
        run.id, resource_key="provider:test", capacity=1, ttl_seconds=30, lease_token=lease.token
    )
    assert second.slot == 0
