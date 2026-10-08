from __future__ import annotations

import httpx

from ares.adapters.jev import JevConfig, JevDecisionProvider
from ares.domain.decisions import ClaimVerdict, ResearchTask
from ares.domain.research import EvidencePacket
from datetime import UTC, datetime
from uuid import uuid4


def _provider(payloads: list[dict]) -> JevDecisionProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        body = payloads.pop(0)
        return httpx.Response(200, json=body)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.typesafe.ai"
    )
    return JevDecisionProvider(JevConfig(api_key="test-key"), client=client)


def _packet(text: str = "Evidence directly supports the claim.") -> EvidencePacket:
    return EvidencePacket(
        evidence_id=uuid4(),
        source_id=uuid4(),
        title="T",
        url="https://example.com/x",
        domain="example.com",
        text=text,
        locator="p1",
        captured_at=datetime.now(UTC),
        content_hash="a" * 64,
    )


def test_jev_route_parses_typed_decisions():
    provider = _provider(
        [
            {
                "model": "jev-latest",
                "answers": {
                    "task": {
                        "type": "choice",
                        "choice": "literature",
                        "confidence": 0.91,
                        "probabilities": {"literature": 0.91},
                    },
                    "academic": {"type": "noul", "noul": 0.98},
                    "software": {"type": "noul", "noul": 0.02},
                    "current_web": {"type": "noul", "noul": 0.61},
                },
                "usage": {"input_tokens": 30, "output_tokens": 6},
            }
        ]
    )
    decision = provider.route("compare recent memory papers")
    assert decision.task is ResearchTask.LITERATURE
    assert decision.needs_academic is True
    assert decision.provider.startswith("jev:")


def test_jev_claim_support_is_typed():
    provider = _provider(
        [
            {
                "model": "jev-latest",
                "answers": {
                    "support": {
                        "type": "choice",
                        "choice": "supported",
                        "confidence": 0.88,
                        "probabilities": {"supported": 0.88},
                    }
                },
                "usage": {"input_tokens": 20, "output_tokens": 3},
            }
        ]
    )
    decision = provider.evaluate_claim("claim", [_packet()])
    assert decision.verdict is ClaimVerdict.SUPPORTED
    assert decision.confidence == 0.88
