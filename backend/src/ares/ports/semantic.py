from __future__ import annotations

from typing import Protocol

from ares.domain.decisions import ClaimDecision
from ares.domain.research import EvidencePacket


class SemanticClaimChecker(Protocol):
    def assess_claim(
        self,
        claim: str,
        evidence: list[EvidencePacket],
        *,
        timeout_seconds: float | None = None,
    ) -> ClaimDecision: ...
