from __future__ import annotations

from pathlib import Path

from ares.adapters.db import Base, build_session_factory
from ares.application.engine import ResearchEngine
from ares.application.repository import Repository
from ares.domain.models import RunCreate, RunMode, RunStatus, SynthesizedClaim, SynthesisResult
from ares.domain.research import EvidencePacket

from test_live_engine_contract import FakeSearch, TrackingFetcher


class SummaryLeakLLM:
    def synthesize(self, query: str, evidence: list[EvidencePacket], *, max_output_tokens: int) -> SynthesisResult:
        return SynthesisResult(
            summary_markdown=(
                "### Model draft\n\nThe first fixture supports this claim. "
                "REJECTED ASSERTION: the fixture accuracy is 10 percent."
            ),
            claims=[
                SynthesizedClaim(
                    text="The first fixture supports this claim.", evidence_ids=[evidence[0].evidence_id]
                ),
                SynthesizedClaim(
                    text="The fixture accuracy is 10 percent.", evidence_ids=[evidence[0].evidence_id]
                ),
            ],
            gaps=[],
        )


def test_rejected_claim_cannot_survive_visible_summary(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'answer.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = Repository(sessions)
    conversation = repository.create_conversation("Answer consistency")
    run, _ = repository.create_run(
        RunCreate(conversation_id=conversation.id, query="What does the fixture support?", mode=RunMode.QUICK),
        idempotency_key="m07-answer",
    )
    lease = repository.claim_next_job()
    assert lease is not None

    ResearchEngine(
        repository,
        FakeSearch(),
        TrackingFetcher(),
        SummaryLeakLLM(),
        gemini_model="fixture-model",
        gemini_rpm=10,
        gemini_tpm=100_000,
        gemini_rpd=100,
    ).execute(lease)
    repository.finish_job(lease)

    snapshot = repository.get_run(run.id)
    assert snapshot.status is RunStatus.COMPLETED
    block = snapshot.answer_blocks[0]
    assert "REJECTED ASSERTION" not in block.markdown
    assert "10 percent" not in block.markdown
    assert [claim.text for claim in block.claims] == ["The first fixture supports this claim."]
