from typing import Protocol
from ares.domain.research import EvidencePacket

class CandidateReranker(Protocol):
    def rerank(self, query: str, candidates: list[EvidencePacket], max_results: int) -> list[EvidencePacket]:
        ...
