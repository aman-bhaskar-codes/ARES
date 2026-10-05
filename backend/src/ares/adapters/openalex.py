from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from ares.domain.models import FetchedDocument, SearchHit
from ares.ports.errors import ProviderRateLimitError, SearchProviderError


def _abstract_from_inverted(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positioned: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions:
            positioned.append((int(position), word))
    positioned.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned)


class OpenAlexAcademicProvider:
    """OpenAlex metadata/abstract adapter.

    This adapter never labels metadata or an abstract as full-text reading. The extraction method
    carried into provenance makes that limitation inspectable downstream.
    """

    def __init__(self, api_key: str = "", *, base_url: str = "https://api.openalex.org", client: httpx.Client | None = None):
        self.api_key = api_key.strip()
        self._client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=20.0)
        self._owns_client = client is None

    def search_documents(
        self, query: str, *, limit: int = 6, timeout_seconds: float | None = None,
        published_after: datetime | None = None, published_before: datetime | None = None,
    ) -> list[tuple[SearchHit, FetchedDocument]]:
        params = {
            "search": query,
            "per_page": min(max(limit, 1), 20),
            "select": "id,doi,title,publication_year,publication_date,abstract_inverted_index,primary_location,best_oa_location,type",
        }
        filters: list[str] = []
        if published_after is not None:
            filters.append(f"from_publication_date:{published_after.date().isoformat()}")
        if published_before is not None:
            filters.append(f"to_publication_date:{published_before.date().isoformat()}")
        if filters:
            params["filter"] = ",".join(filters)
        if self.api_key:
            params["api_key"] = self.api_key
        try:
            response = self._client.get("/works", params=params, timeout=timeout_seconds) if timeout_seconds is not None else self._client.get("/works", params=params)
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"OpenAlex request failed: {type(exc).__name__}") from exc
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            raise ProviderRateLimitError(
                "OpenAlex free allowance exhausted or rate limited",
                retry_after_seconds=float(retry) if retry and retry.isdigit() else None,
            )
        if response.status_code >= 400:
            raise SearchProviderError(f"OpenAlex returned HTTP {response.status_code}")
        try:
            rows = response.json().get("results", [])
        except ValueError as exc:
            raise SearchProviderError("OpenAlex returned invalid JSON") from exc

        output: list[tuple[SearchHit, FetchedDocument]] = []
        for rank, row in enumerate(rows[:limit], start=1):
            title = (row.get("title") or "Untitled work").strip()
            abstract = _abstract_from_inverted(row.get("abstract_inverted_index"))
            if not abstract:
                continue
            openalex_id = row.get("id") or ""
            doi = row.get("doi") or ""
            primary = (row.get("primary_location") or {}).get("landing_page_url") or ""
            best_oa = row.get("best_oa_location") or {}
            # OpenAlex documents best_oa_location as the best freely readable copy. Prefer a
            # direct PDF URL when supplied; a landing page is metadata, not full text.
            full_text_url = best_oa.get("pdf_url") or ""
            url = doi or primary or openalex_id
            if not url.startswith("http"):
                continue
            published_at = None
            raw_date = row.get("publication_date")
            if raw_date:
                try:
                    published_at = datetime.fromisoformat(raw_date).replace(tzinfo=UTC)
                except ValueError:
                    pass
            text = f"{title}\n\nAbstract\n{abstract}"
            source_id = uuid4()
            canonical_identifier = f"doi:{doi.removeprefix('https://doi.org/').lower()}" if doi else f"openalex:{openalex_id.rsplit('/', 1)[-1]}"
            hit = SearchHit(
                title=title,
                url=url,
                snippet=abstract[:500],
                rank=rank,
                provider="openalex",
                engine="openalex",
                source_kind="academic",
                canonical_identifier=canonical_identifier,
                published_at=published_at,
                full_text_url=full_text_url if isinstance(full_text_url, str) and full_text_url.startswith("http") else None,
                full_text_mime_type="application/pdf" if isinstance(full_text_url, str) and full_text_url.startswith("http") else None,
            )
            document = FetchedDocument(
                source_id=source_id,
                title=title,
                url=url,
                final_url=url,
                text=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                fetched_at=datetime.now(UTC),
                extraction_method="openalex-metadata-abstract",
                mime_type="application/vnd.openalex.work+json",
                byte_count=len(text.encode("utf-8")),
                source_kind="academic",
                canonical_identifier=canonical_identifier,
                published_at=published_at,
            )
            output.append((hit, document))
        return output

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
