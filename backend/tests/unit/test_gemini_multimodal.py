from __future__ import annotations

from dataclasses import dataclass

import pytest

from ares.adapters.gemini_multimodal import (
    GeminiMultimodalUnderstandingProvider,
    MultimodalProviderUnavailable,
)
from ares.ports.multimodal import MediaRegionInput


@dataclass
class _Response:
    text: str


class _Models:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.text)


class _Client:
    def __init__(self, text: str) -> None:
        self.models = _Models(text)


def test_multimodal_adapter_preserves_only_server_supplied_region_ids() -> None:
    client = _Client('{"observations":[{"region_id":"frame-1200","description":"A chart title is visible."}]}')
    provider = GeminiMultimodalUnderstandingProvider(
        "",
        client=client,
        part_factory=lambda data, mime: {"bytes": len(data), "mime": mime},
    )
    result = provider.describe_regions(
        "Read visible chart text",
        [MediaRegionInput(region_id="frame-1200", mime_type="image/jpeg", data=b"jpeg")],
        max_output_tokens=256,
    )
    assert result[0].region_id == "frame-1200"
    assert result[0].text == "A chart title is visible."
    call = client.models.calls[0]
    assert call["model"] == "gemini-3.8-flash"
    assert "REGION_ID=frame-1200" in call["contents"]


def test_multimodal_adapter_rejects_model_invented_region_identity() -> None:
    provider = GeminiMultimodalUnderstandingProvider(
        "",
        client=_Client('{"observations":[{"region_id":"invented","description":"guess"}]}'),
        part_factory=lambda data, mime: object(),
    )
    with pytest.raises(MultimodalProviderUnavailable, match="unknown media region"):
        provider.describe_regions(
            "Describe",
            [MediaRegionInput(region_id="known", mime_type="image/jpeg", data=b"jpeg")],
            max_output_tokens=128,
        )


def test_multimodal_adapter_enforces_small_explicit_batch() -> None:
    provider = GeminiMultimodalUnderstandingProvider(
        "", client=_Client('{"observations":[]}'), part_factory=lambda data, mime: object()
    )
    regions = [
        MediaRegionInput(region_id=f"r-{index}", mime_type="image/jpeg", data=b"x")
        for index in range(9)
    ]
    with pytest.raises(ValueError, match="at most 8"):
        provider.describe_regions("Describe", regions, max_output_tokens=128)
