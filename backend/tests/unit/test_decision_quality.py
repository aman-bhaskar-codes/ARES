from datetime import UTC, datetime
from uuid import uuid4

from ares.application.decisions import DeterministicDecisionProvider, ResilientDecisionProvider
from ares.domain.decisions import ClaimVerdict, ResearchTask
from ares.domain.research import EvidencePacket


def packet(text: str) -> EvidencePacket:
    return EvidencePacket(
        evidence_id=uuid4(),
        source_id=uuid4(),
        title="source",
        url="https://example.com",
        domain="example.com",
        text=text,
        locator="passage",
        captured_at=datetime.now(UTC),
        content_hash="a" * 64,
    )


def test_document_routing_detects_explicit_user_document_intent() -> None:
    decision = DeterministicDecisionProvider().route(
        "Summarize the limitations in this uploaded document"
    )
    assert decision.task is ResearchTask.DOCUMENT
    assert decision.needs_current_web is False


def test_claim_fallback_can_support_high_overlap_claim() -> None:
    decision = DeterministicDecisionProvider().evaluate_claim(
        "HNSW uses more memory and has slower build times than IVFFlat.",
        [
            packet(
                "HNSW has slower build times and uses more memory than IVFFlat, while offering a better speed-recall tradeoff."
            )
        ],
    )
    assert decision.verdict is ClaimVerdict.SUPPORTED


def test_claim_fallback_rejects_unrelated_evidence() -> None:
    decision = DeterministicDecisionProvider().evaluate_claim(
        "The system reduced latency by 40 percent.",
        [
            packet(
                "The paper discusses qualitative interview coding and participant recruitment methods."
            )
        ],
    )
    assert decision.verdict is ClaimVerdict.INSUFFICIENT


def test_claim_fallback_surfaces_conflicting_evidence() -> None:
    claim = "The new index increased retrieval latency."
    decision = DeterministicDecisionProvider().evaluate_claim(
        claim,
        [
            packet("The new index increased retrieval latency in the large corpus."),
            packet("The new index decreased retrieval latency in the large corpus."),
        ],
    )
    assert decision.verdict is ClaimVerdict.CONFLICTING


def test_numeric_mismatch_10_vs_90_is_never_supported() -> None:
    decision = DeterministicDecisionProvider().evaluate_claim(
        "The trial improved accuracy to 10 percent.",
        [packet("The trial improved accuracy to 90 percent.")],
    )
    assert decision.verdict in {ClaimVerdict.INSUFFICIENT, ClaimVerdict.CONFLICTING}
    assert decision.assessment_state.value == "deterministic_exact"


def test_percent_and_percentage_points_are_not_interchangeable() -> None:
    decision = DeterministicDecisionProvider().evaluate_claim(
        "The rate increased by 10 percentage points.",
        [packet("The rate increased by 10 percent.")],
    )
    assert decision.verdict in {ClaimVerdict.INSUFFICIENT, ClaimVerdict.CONFLICTING}
    assert decision.assessment_state.value == "deterministic_exact"


def test_semantic_checker_cannot_override_exact_numeric_guard() -> None:
    class AlwaysSupports:
        def route(self, query):  # pragma: no cover - not used
            raise AssertionError

        def evaluate_coverage(self, query, facets, evidence):  # pragma: no cover - not used
            raise AssertionError

        def evaluate_claim(self, claim, evidence):
            from ares.domain.decisions import ClaimDecision

            return ClaimDecision(
                verdict=ClaimVerdict.SUPPORTED,
                confidence=1.0,
                provider="unsafe-test",
                checker_method="semantic",
                assessment_state="semantic_assessed",
            )

    decision = ResilientDecisionProvider(AlwaysSupports()).evaluate_claim(
        "The trial improved accuracy to 10 percent.",
        [packet("The trial improved accuracy to 90 percent.")],
    )
    assert decision.verdict is not ClaimVerdict.SUPPORTED
    assert decision.checker_method == "deterministic_numeric_unit_guard"


def test_numeric_guard_rejects_10_vs_90_counterexample() -> None:
    decision = DeterministicDecisionProvider().evaluate_claim(
        "The trial improved accuracy to 90 percent.",
        [packet("The trial improved accuracy to 10 percent.")],
    )
    assert decision.verdict is ClaimVerdict.INSUFFICIENT
    assert decision.checker_method == "deterministic_numeric_unit_guard"
    assert decision.assessment_state == "deterministic_exact"


def test_numeric_guard_distinguishes_percent_from_percentage_points() -> None:
    decision = DeterministicDecisionProvider().evaluate_claim(
        "The margin increased by 10 percentage points.",
        [packet("The margin increased by 10 percent.")],
    )
    assert decision.verdict is ClaimVerdict.INSUFFICIENT


def test_numeric_guard_rejects_incompatible_date() -> None:
    decision = DeterministicDecisionProvider().evaluate_claim(
        "The study was published in 2024.",
        [packet("The study was published in 2023.")],
    )
    assert decision.verdict is ClaimVerdict.INSUFFICIENT
