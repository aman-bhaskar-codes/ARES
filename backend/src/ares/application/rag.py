from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal, Protocol

from ares.domain.models import FetchedDocument
from ares.domain.research import EvidenceCandidate

_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


class EmbeddingProvider(Protocol):
    def embed_query(self, text: str) -> list[float]: ...
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class RAGConfig:
    target_chars: int = 1_400
    overlap_chars: int = 180
    min_chunk_chars: int = 220
    max_chunks_per_source: int = 3
    lexical_weight: float = 0.7
    semantic_weight: float = 0.3
    reciprocal_rank_k: int = 60
    diversity_penalty: float = 0.18
    mode: Literal["lexical", "semantic", "hybrid"] = "hybrid"


@dataclass(frozen=True, slots=True)
class RetrievalTraceItem:
    candidate_id: str
    source_id: str
    lexical_rank: int
    semantic_rank: int | None
    fused_rank: int
    lexical_score: float
    semantic_score: float | None
    combined_score: float


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    candidates: list[EvidenceCandidate]
    mode: str
    semantic_used: bool
    trace: list[RetrievalTraceItem]


def _tokens(text: str) -> list[str]:
    return [m.group(0).casefold() for m in _TOKEN.finditer(text) if len(m.group(0)) > 1]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def chunk_document(doc: FetchedDocument, config: RAGConfig | None = None) -> list[EvidenceCandidate]:
    config = config or RAGConfig()
    text = doc.text.strip()
    if not text:
        return []

    # Paragraph boundaries are preferred. Very long paragraphs fall back to sentence boundaries.
    pieces: list[tuple[int, int]] = []
    cursor = 0
    paragraphs = re.split(r"\n\s*\n+", text)
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        start = text.find(paragraph, cursor)
        if start < 0:
            start = cursor
        end = start + len(paragraph)
        cursor = end
        if len(paragraph) <= config.target_chars * 2:
            pieces.append((start, end))
            continue
        local = 0
        for sentence in _SENTENCE_BOUNDARY.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            s = paragraph.find(sentence, local)
            if s < 0:
                s = local
            pieces.append((start + s, start + s + len(sentence)))
            local = s + len(sentence)

    chunks: list[tuple[int, int]] = []
    chunk_start: int | None = None
    chunk_end: int | None = None
    for start, end in pieces:
        if chunk_start is None:
            chunk_start, chunk_end = start, end
            continue
        assert chunk_end is not None
        projected = end - chunk_start
        if projected <= config.target_chars or (chunk_end - chunk_start) < config.min_chunk_chars:
            chunk_end = end
            continue
        chunks.append((chunk_start, chunk_end))
        overlap_target = max(chunk_start, chunk_end - config.overlap_chars)
        chunk_start = overlap_target
        chunk_end = end
    if chunk_start is not None and chunk_end is not None:
        chunks.append((chunk_start, chunk_end))

    result: list[EvidenceCandidate] = []
    for index, (start, end) in enumerate(chunks, start=1):
        excerpt = text[start:end].strip()
        if len(excerpt) < config.min_chunk_chars and len(chunks) > 1:
            continue
        pages = [
            int(item["page"])
            for item in doc.page_map
            if int(item["char_end"]) >= start and int(item["char_start"]) <= end
        ]
        page_start = min(pages) if pages else None
        page_end = max(pages) if pages else None
        if page_start is None:
            locator = f"extracted text · passage {index}"
        elif page_start == page_end:
            locator = f"p. {page_start} · passage {index}"
        else:
            locator = f"pp. {page_start}–{page_end} · passage {index}"
        result.append(
            EvidenceCandidate(
                source_id=doc.source_id,
                title=doc.title,
                url=doc.final_url,
                text=excerpt,
                locator=locator,
                char_start=start,
                char_end=end,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return result


class HybridRAGRetriever:
    """Evidence retriever with deterministic lexical ranking and optional semantic fusion.

    The default path has no network/model dependency. When an embedding provider is explicitly
    configured, semantic scores are fused with lexical relevance; source diversity is enforced
    afterwards so one verbose page cannot monopolize the synthesis context.
    """

    def __init__(self, *, config: RAGConfig | None = None, embedder: EmbeddingProvider | None = None):
        self.config = config or RAGConfig()
        self.embedder = embedder

    def retrieve(
        self, query: str, documents: list[FetchedDocument], *, limit: int
    ) -> list[EvidenceCandidate]:
        return self.retrieve_with_trace(query, documents, limit=limit).candidates

    def retrieve_with_trace(
        self, query: str, documents: list[FetchedDocument], *, limit: int
    ) -> RetrievalResult:
        candidates = [candidate for doc in documents for candidate in chunk_document(doc, self.config)]
        if not candidates:
            return RetrievalResult(candidates=[], mode=self.config.mode, semantic_used=False, trace=[])

        query_terms = _tokens(query)
        query_counts = Counter(query_terms)
        doc_terms = [_tokens(candidate.text) for candidate in candidates]
        document_frequency: Counter[str] = Counter()
        for terms in doc_terms:
            document_frequency.update(set(terms))
        total = len(candidates)

        lexical_raw: list[float] = []
        for candidate, terms in zip(candidates, doc_terms, strict=True):
            counts = Counter(terms)
            length_norm = 1.0 + 0.25 * max(0.0, len(terms) / 220 - 1.0)
            score = 0.0
            for term, qtf in query_counts.items():
                tf = counts.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1.0 + (total + 1) / (document_frequency[term] + 1))
                score += qtf * idf * (tf / (tf + 1.2 * length_norm))
            phrase = " ".join(query_terms[:8])
            if phrase and phrase in candidate.text.casefold():
                score += 1.25
            lexical_raw.append(score)

        lexical = _normalize(lexical_raw)
        semantic: list[float] | None = None
        semantic_required = self.config.mode in {"semantic", "hybrid"}
        if semantic_required and self.embedder is not None:
            query_vector = self.embedder.embed_query(query)
            vectors = self.embedder.embed_documents([candidate.text for candidate in candidates])
            semantic = _normalize([max(0.0, _cosine(query_vector, vector)) for vector in vectors])

        lexical_order = sorted(range(len(candidates)), key=lambda i: lexical[i], reverse=True)
        lexical_rank = {index: rank for rank, index in enumerate(lexical_order, start=1)}
        semantic_rank: dict[int, int] = {}
        if semantic is not None:
            semantic_order = sorted(range(len(candidates)), key=lambda i: semantic[i], reverse=True)
            semantic_rank = {index: rank for rank, index in enumerate(semantic_order, start=1)}

        if self.config.mode == "semantic" and semantic is not None:
            combined = semantic
        elif self.config.mode == "hybrid" and semantic is not None:
            # Reciprocal Rank Fusion is robust to score-scale differences between lexical and
            # embedding retrievers. Ranking depends on ranks, not calibrated score magnitudes.
            k = self.config.reciprocal_rank_k
            rrf_raw = [
                self.config.lexical_weight / (k + lexical_rank[index])
                + self.config.semantic_weight / (k + semantic_rank[index])
                for index in range(len(candidates))
            ]
            combined = _normalize(rrf_raw)
        else:
            # Lexical is the fail-closed fallback when semantic retrieval is disabled or its
            # provider is not configured. `semantic` mode therefore degrades visibly rather than
            # making the whole research path unavailable.
            combined = lexical

        for index, candidate in enumerate(candidates):
            candidate.lexical_score = lexical[index]
            candidate.semantic_score = semantic[index] if semantic is not None else None
            candidate.combined_score = combined[index]

        ranked = sorted(candidates, key=lambda item: item.combined_score, reverse=True)
        fused_rank_by_id = {candidate.candidate_id: rank for rank, candidate in enumerate(ranked, start=1)}
        minimum_context = min(3, limit, len(candidates))
        selected: list[EvidenceCandidate] = []
        per_source: defaultdict[object, int] = defaultdict(int)
        while ranked and len(selected) < limit:
            best_index = 0
            best_score = -math.inf
            for index, candidate in enumerate(ranked):
                if per_source[candidate.source_id] >= self.config.max_chunks_per_source:
                    continue
                candidate_terms = set(_tokens(candidate.text))
                overlap = 0.0
                for chosen in selected:
                    chosen_terms = set(_tokens(chosen.text))
                    union = candidate_terms | chosen_terms
                    if union:
                        overlap = max(overlap, len(candidate_terms & chosen_terms) / len(union))
                adjusted = candidate.combined_score - self.config.diversity_penalty * overlap
                if adjusted > best_score:
                    best_score = adjusted
                    best_index = index
            candidate = ranked.pop(best_index)
            if per_source[candidate.source_id] >= self.config.max_chunks_per_source:
                if all(per_source[item.source_id] >= self.config.max_chunks_per_source for item in ranked):
                    break
                continue
            if candidate.combined_score <= 0 and len(selected) >= minimum_context:
                break
            selected.append(candidate)
            per_source[candidate.source_id] += 1

        trace = [
            RetrievalTraceItem(
                candidate_id=str(candidate.candidate_id),
                source_id=str(candidate.source_id),
                lexical_rank=lexical_rank[index],
                semantic_rank=semantic_rank.get(index),
                fused_rank=fused_rank_by_id[candidate.candidate_id],
                lexical_score=lexical[index],
                semantic_score=semantic[index] if semantic is not None else None,
                combined_score=combined[index],
            )
            for index, candidate in enumerate(candidates)
        ]
        return RetrievalResult(
            candidates=selected,
            mode=self.config.mode if semantic is not None or self.config.mode == "lexical" else "lexical_fallback",
            semantic_used=semantic is not None,
            trace=trace,
        )
