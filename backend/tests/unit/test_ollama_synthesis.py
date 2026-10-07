from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from ares.adapters.ollama_synthesis import OllamaLLMProvider
from ares.adapters.gemini import ProviderUnavailable
from ares.domain.research import EvidencePacket


def test_local_writer_grounds_claims_and_disables_thinking():
    packet = EvidencePacket(
        evidence_id=uuid4(),
        source_id=uuid4(),
        title="Test",
        url="https://example.com",
        domain="example.com",
        text="Context. " * 90 + "The test color is blue.",
        locator="test",
        captured_at=datetime.now(UTC),
        content_hash="a" * 64,
    )

    def respond(request):
        import json

        body = json.loads(request.content)
        assert body["think"] is False
        assert body["stream"] is False
        assert body["format"]["properties"]["claims"]["maxItems"] == 8
        assert body["options"]["num_predict"] == 1600
        assert "The test color is blue." in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": '{"summary_markdown":"The test color is blue.","claims":[{"text":"The test color is blue.","evidence_indexes":[0]}]}'
                }
            },
        )

    provider = OllamaLLMProvider(client=httpx.Client(transport=httpx.MockTransport(respond)))
    result = provider.synthesize(
        "What color?", [packet], max_output_tokens=2000, timeout_seconds=10
    )
    assert result.claims[0].evidence_ids == [packet.evidence_id]
    provider.close()


def test_local_writer_outage_is_a_provider_error():
    provider = OllamaLLMProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    )
    packet = EvidencePacket(
        evidence_id=uuid4(),
        source_id=uuid4(),
        title="Test",
        url="https://example.com",
        domain="example.com",
        text="Blue.",
        locator="test",
        captured_at=datetime.now(UTC),
        content_hash="a" * 64,
    )
    with pytest.raises(ProviderUnavailable):
        provider.synthesize("What color?", [packet], max_output_tokens=256, timeout_seconds=10)
    provider.close()
