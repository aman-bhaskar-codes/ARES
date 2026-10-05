from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ares.domain.models import FetchedDocument, SearchHit, SynthesisResult
from ares.domain.research import EvidencePacket, SearchRequest


class SearchProvider(Protocol):
    def search(self, request: SearchRequest) -> list[SearchHit]: ...


class Fetcher(Protocol):
    def fetch(self, url: str, *, timeout_seconds: float | None = None) -> FetchedDocument: ...


class AcademicFullTextFetcher(Protocol):
    def fetch_pdf(
        self, url: str, *, timeout_seconds: float | None = None, max_bytes: int = ...,
        max_pages: int = ..., max_text_chars: int = ...
    ) -> FetchedDocument: ...


class LLMProvider(Protocol):
    def synthesize(
        self, query: str, evidence: list[EvidencePacket], *, max_output_tokens: int, timeout_seconds: float | None = None
    ) -> SynthesisResult: ...


class AcademicProvider(Protocol):
    def search_documents(
        self, query: str, *, limit: int = 6, timeout_seconds: float | None = None,
        published_after: datetime | None = None, published_before: datetime | None = None,
    ) -> list[tuple[SearchHit, FetchedDocument]]: ...


class SoftwareProvider(Protocol):
    def search_documents(
        self, query: str, *, limit: int = 5, timeout_seconds: float | None = None,
        published_after: datetime | None = None, published_before: datetime | None = None,
    ) -> list[tuple[SearchHit, FetchedDocument]]: ...
