from __future__ import annotations

from typing import Protocol

from ares.domain.decisions import ClaimDecision, CoverageDecision, RouteDecision
from ares.domain.research import EvidencePacket


class DecisionProvider(Protocol):
    def route(self, query: str) -> RouteDecision: ...

    def evaluate_coverage(
        self, query: str, facets: list[str], evidence: list[EvidencePacket]
    ) -> CoverageDecision: ...

    def evaluate_claim(self, claim: str, evidence: list[EvidencePacket]) -> ClaimDecision: ...
