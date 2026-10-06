from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

import httpx

from ares.application.providers import DiscoveryProvider, ProviderMetadata, ProviderCapabilities
from ares.domain.models import FetchedDocument, SearchHit
from ares.domain.research import SearchRequest
from ares.ports.errors import ProviderRateLimitError, SearchProviderError


class SearXNGSearchProvider(DiscoveryProvider):
    def __init__(
        self, base_url: str, timeout_seconds: float = 10.0, *, client: httpx.Client | None = None
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="searxng",
            source_kind="web",
            capabilities=ProviderCapabilities(
                supports_time_range=True,
                supports_full_text=False,
                supports_exact_id=False,
            ),
            cost_class="free",
            timeout_seconds=self.timeout_seconds,
            rate_limit_rpm=None,
            cache_ttl_seconds=3600,
        )

    def search_documents(
        self,
        query: str,
        limit: int,
        *,
        timeout_seconds: float | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
    ) -> list[tuple[SearchHit, FetchedDocument | None]]:
        # Map time range roughly if needed, or rely on engine to pass the string
        req = SearchRequest(query=query, limit=limit, timeout_seconds=timeout_seconds)
        hits = self.search(req)
        return [(hit, None) for hit in hits]

    def search(self, request: SearchRequest) -> list[SearchHit]:
        endpoint = urljoin(self.base_url, "search")
        params: dict[str, object] = {
            "q": request.query,
            "format": "json",
            "safesearch": 1,
            "language": request.language,
        }
        if request.time_range is not None:
            params["time_range"] = request.time_range
        try:
            if request.timeout_seconds is None:
                response = self._client.get(endpoint, params=params)
            else:
                try:
                    response = self._client.get(
                        endpoint, params=params, timeout=request.timeout_seconds
                    )
                except TypeError as exc:
                    if "timeout" not in str(exc):
                        raise
                    # Compatibility for injected M06 clients in tests/extensions. The
                    # production httpx client supports the per-request timeout.
                    response = self._client.get(endpoint, params=params)
            if getattr(response, "status_code", 200) == 429:
                retry = getattr(response, "headers", {}).get("Retry-After")
                raise ProviderRateLimitError(
                    "SearXNG rate limit reached",
                    retry_after_seconds=float(retry) if retry and retry.isdigit() else None,
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchProviderError("SearXNG search failed") from exc
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise SearchProviderError("SearXNG returned an invalid results payload")

        hits: list[SearchHit] = []
        for index, item in enumerate(results, start=1):
            if len(hits) >= request.limit:
                break
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            title = item.get("title")
            if not isinstance(url, str) or not isinstance(title, str):
                continue
            published_at = None
            raw_date = item.get("publishedDate") or item.get("published_date")
            if isinstance(raw_date, str):
                try:
                    published_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    published_at = None
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    snippet=str(item.get("content") or ""),
                    rank=index,
                    provider="searxng",
                    engine=str(item.get("engine")) if item.get("engine") else None,
                    source_kind="web",
                    published_at=published_at,
                )
            )
        return hits

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
