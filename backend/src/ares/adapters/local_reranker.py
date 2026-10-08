from ares.ports.reranking import CandidateReranker
from ares.domain.research import EvidencePacket

class LocalCrossEncoderReranker(CandidateReranker):
    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2", cache_dir: str | None = None, threads: int | None = None):
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._encoder = TextCrossEncoder(model_name=model_name, cache_dir=cache_dir, threads=threads)
        except ImportError:
            self._encoder = None
            
    def rerank(self, query: str, candidates: list[EvidencePacket], max_results: int) -> list[EvidencePacket]:
        if not self._encoder or not candidates:
            return candidates[:max_results]
        
        texts = [c.text for c in candidates]
        scores = list(self._encoder.rerank(query, texts))
        
        # Enumerate to keep original index, sort by score descending
        scored_candidates = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        return [c for score, c in scored_candidates][:max_results]
