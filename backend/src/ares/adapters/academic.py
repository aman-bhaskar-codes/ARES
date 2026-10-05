from __future__ import annotations

from datetime import datetime
from ares.domain.models import FetchedDocument, SearchHit
from ares.ports.errors import SearchProviderError


class CompositeAcademicProvider:
    """Merge several read-only scholarly metadata adapters with deterministic deduplication."""

    def __init__(self, providers: list):
        self.providers = providers

    def search_documents(
        self, query: str, *, limit: int = 8, timeout_seconds: float | None = None,
        published_after: datetime | None = None, published_before: datetime | None = None,
    ) -> list[tuple[SearchHit, FetchedDocument]]:
        collected: list[tuple[SearchHit, FetchedDocument]] = []
        errors: list[str] = []
        per_provider = max(2, min(limit, 6))
        for provider in self.providers:
            try:
                try:
                    rows = provider.search_documents(
                        query, limit=per_provider, timeout_seconds=timeout_seconds,
                        published_after=published_after, published_before=published_before,
                    )
                except TypeError as exc:
                    # Preserve compatibility with M06 third-party adapters while the M07
                    # date-aware port rolls out. Built-in adapters implement the full contract.
                    if "published_after" not in str(exc) and "published_before" not in str(exc):
                        raise
                    rows = provider.search_documents(query, limit=per_provider, timeout_seconds=timeout_seconds)
                collected.extend(rows)
            except SearchProviderError as exc:
                errors.append(str(exc))
        if not collected and errors:
            raise SearchProviderError("; ".join(errors[:3]))

        deduped: dict[str, tuple[SearchHit, FetchedDocument]] = {}
        for hit, document in collected:
            key = document.canonical_identifier or str(document.final_url).casefold()
            if key not in deduped:
                deduped[key] = (hit, document)
        # Re-rank after cross-provider deduplication so persisted discovery rank is meaningful.
        output: list[tuple[SearchHit, FetchedDocument]] = []
        for rank, (hit, document) in enumerate(deduped.values(), start=1):
            if rank > limit:
                break
            output.append((hit.model_copy(update={"rank": rank}), document))
        return output

    def close(self) -> None:
        for provider in self.providers:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
