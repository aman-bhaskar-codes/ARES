from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ares.adapters.db import Base, build_session_factory
from ares.application.engine import ResearchEngine
from ares.application.repository import Repository
from ares.domain.models import (
    FetchedDocument,
    RunCreate,
    RunMode,
    RunStatus,
    SearchHit,
    SynthesizedClaim,
    SynthesisResult,
)
from ares.domain.research import EvidencePacket, SearchRequest


class FakeSearch:
    def search(self, request: SearchRequest) -> list[SearchHit]:
        return [
            SearchHit(title=f"Source {i}", url=f"https://example.com/{i}", rank=i)
            for i in range(1, 4)
        ]


class FakeFetcher:
    def fetch(self, url: str, *, timeout_seconds: float | None = None) -> FetchedDocument:
        return FetchedDocument(
            source_id=uuid4(),
            title=url.rsplit("/", 1)[-1],
            url=url,
            final_url=url,
            text="The fixture evidence supports 100 computational claims and 10 calculation proofs for quantum limits.",
            content_hash=url.rsplit("/", 1)[-1].zfill(64),
            fetched_at=datetime.now(UTC),
            extraction_method="fixture",
        )


class FakeLLM:
    def synthesize(
        self, query: str, evidence: list[EvidencePacket], *, max_output_tokens: int, timeout_seconds: float | None = None
    ) -> SynthesisResult:
        return SynthesisResult(
            summary_markdown="Structured claims with technical computation.",
            claims=[
                SynthesizedClaim(
                    text="The fixture evidence supports 100 computational claims and 10 calculation proofs.\n```python\nprint(10 * 10)\n```",
                    evidence_ids=[evidence[0].evidence_id],
                )
            ],
            gaps=[],
        )


def test_research_engine_executes_plugins_end_to_end(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'plugins_test.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = Repository(sessions)
    conversation = repository.create_conversation("Plugin Test Conversation")

    run, _ = repository.create_run(
        RunCreate(
            conversation_id=conversation.id,
            query="Calculate 25 * 4 and analyze quantum limits",
            mode=RunMode.QUICK,
            plugins=["speed", "accuracy", "code"],
        ),
        idempotency_key="plugin-run-1",
    )
    assert run.plugins == ["speed", "accuracy", "code"]

    lease = repository.claim_next_job()
    assert lease is not None

    ResearchEngine(
        repository,
        FakeSearch(),
        FakeFetcher(),
        FakeLLM(),
        gemini_model="fixture-model",
        gemini_rpm=10,
        gemini_tpm=100_000,
        gemini_rpd=100,
    ).execute(lease)
    repository.finish_job(lease)

    snapshot = repository.get_run(run.id)
    assert snapshot.status is RunStatus.COMPLETED
    assert snapshot.plugins == ["speed", "accuracy", "code"]

    events = repository.list_events(run.id)
    event_names = [e.event_type for e in events]

    assert "plugins.activated" in event_names
    assert "plugin.speed.applied" in event_names
    assert "plugin.accuracy.applied" in event_names
    assert "plugin.code.applied" in event_names
    assert "code_interpreter.executed" in event_names

    # Check interpreter execution details
    code_events = [e for e in events if e.event_type == "code_interpreter.executed"]
    assert len(code_events) >= 1
    # Check that at least one event produced stdout "100" (from 25 * 4 or 10 * 10)
    assert any("100" in str(e.payload.get("stdout", "")) for e in code_events)
