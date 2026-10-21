"""Transport-independent contract for grounded answer writers."""
from typing import Any, Protocol

from ares.domain.models import SynthesisResult
from ares.domain.research import EvidencePacket


class ModelProvider(Protocol):
    def synthesize(self, query: str, evidence: list[EvidencePacket], *,
                   max_output_tokens: int, timeout_seconds: float | None = None) -> SynthesisResult: ...
    def manifest(self) -> dict[str, Any]: ...
    def close(self) -> None: ...
