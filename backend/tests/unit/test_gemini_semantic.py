from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ares.adapters.gemini_semantic import GeminiSemanticClaimChecker, SemanticCheckerUnavailable
from ares.domain.models import AssessmentState
from ares.domain.research import EvidencePacket


class _Interactions:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text=self.output_text)


class _Client:
    def __init__(self, output_text: str) -> None:
        self.interactions = _Interactions(output_text)


def packet(text: str) -> EvidencePacket:
    return EvidencePacket(
        evidence_id=uuid4(),
        source_id=uuid4(),
        title="fixture",
        url="https://example.com/evidence",
        domain="example.com",
        text=text,
        locator="passage 1",
        captured_at=datetime.now(UTC),
        content_hash="a" * 64,
    )


def test_semantic_checker_returns_typed_support_and_conflict_edges() -> None:
    first = packet("The measured latency was lower.")
    second = packet("A separate benchmark found higher latency.")
    client = _Client(
        '{"verdict":"conflicting","supporting_indexes":[0],"conflicting_indexes":[1],'
        '"rationale":"The supplied benchmarks disagree.","confidence":0.87}'
    )
    checker = GeminiSemanticClaimChecker("", model="fixture", client=client)
    decision = checker.assess_claim("Latency was lower.", [first, second])
    assert decision.assessment_state is AssessmentState.SEMANTIC_ASSESSED
    assert decision.supporting_evidence_ids == [first.evidence_id]
    assert decision.conflicting_evidence_ids == [second.evidence_id]
    assert client.interactions.kwargs["store"] is False
    assert "You have no tools" in client.interactions.kwargs["system_instruction"]


def test_semantic_checker_rejects_invented_evidence_indexes() -> None:
    client = _Client(
        '{"verdict":"supported","supporting_indexes":[7],"conflicting_indexes":[],'
        '"rationale":"bad reference","confidence":0.7}'
    )
    checker = GeminiSemanticClaimChecker("", model="fixture", client=client)
    with pytest.raises(SemanticCheckerUnavailable):
        checker.assess_claim("claim", [packet("evidence")])


def test_consecutive_semantic_checks_reuse_client_event_loop() -> None:
    import asyncio

    class LoopBoundInteractions:
        loop = None

        async def create(self, **kwargs):
            current = asyncio.get_running_loop()
            if self.loop is not None and self.loop is not current:
                raise RuntimeError('Event loop is closed')
            self.loop = current
            return SimpleNamespace(output_text='{"verdict":"supported","supporting_indexes":[0],"conflicting_indexes":[],"rationale":"Supported.","confidence":0.9}')

    checker = GeminiSemanticClaimChecker('', model='fixture', client=SimpleNamespace(aio=SimpleNamespace(interactions=LoopBoundInteractions())))
    evidence = packet('The color is blue.')
    try:
        for _ in range(3):
            decision = checker.assess_claim('The color is blue.', [evidence], timeout_seconds=1)
            assert decision.supporting_evidence_ids == [evidence.evidence_id]
    finally:
        checker.close()
