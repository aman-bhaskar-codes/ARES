from pathlib import Path

from ares.adapters.db import Base, build_session_factory
from ares.application.engine import DemoResearchEngine
from ares.application.repository import Repository
from ares.domain.models import RunCreate, RunMode


def test_run_quality_resolves_citations_and_aggregates_support(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'quality.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = Repository(sessions)
    conversation = repository.create_conversation("quality")
    run, _ = repository.create_run(
        RunCreate(
            conversation_id=conversation.id, query="Summarize ARES provenance", mode=RunMode.QUICK
        ),
        idempotency_key="quality-1",
    )
    lease = repository.claim_next_job()
    assert lease is not None
    DemoResearchEngine(repository).execute(lease)
    repository.finish_job(lease)

    quality = repository.get_run_quality(run.id)
    assert quality.claim_count == 2
    assert quality.evidence_count == 2
    assert quality.citation_resolution_rate == 1.0
    assert quality.claim_citation_rate == 1.0
    assert quality.supported_claim_rate == 1.0
    assert quality.support_counts["supported"] == 2
    assert quality.distinct_source_group_count == 2
    assert quality.queue_wait_ms is not None and quality.queue_wait_ms >= 0
    assert quality.run_elapsed_ms is not None and quality.run_elapsed_ms >= quality.queue_wait_ms
