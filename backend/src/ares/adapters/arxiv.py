from __future__ import annotations

import hashlib
import threading
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from ares.application.providers import DiscoveryProvider, ProviderMetadata, ProviderCapabilities
from ares.domain.models import FetchedDocument, SearchHit
from ares.ports.errors import ProviderRateLimitError, SearchProviderError

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class ArxivAcademicProvider(DiscoveryProvider):
    """Legacy arXiv Atom API adapter with conservative client-side pacing."""

    def __init__(
        self,
        *,
        base_url: str = "https://export.arxiv.org",
        min_interval_seconds: float = 3.0,
        client: httpx.Client | None = None,
    ):
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=25.0,
            headers={"User-Agent": "ARES-research/0.4 (+local research assistant)"},
        )
        self._interval = max(0.0, min_interval_seconds)
        self._owns_client = client is None
        self._lock = threading.Lock()
        self._last_request = 0.0

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="arxiv",
            source_kind="academic",
            capabilities=ProviderCapabilities(
                supports_time_range=True,
                supports_full_text=True,
                supports_exact_id=True,
            ),
            cost_class="free",
            timeout_seconds=25.0,
            rate_limit_rpm=20,  # 3 seconds interval = 20 RPM
            cache_ttl_seconds=604800,
        )

    def _paced_get(self, **kwargs) -> httpx.Response:
        with self._lock:
            delay = self._interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            try:
                response = self._client.get("/api/query", **kwargs)
            except httpx.HTTPError as exc:
                raise SearchProviderError(f"arXiv request failed: {type(exc).__name__}") from exc
            finally:
                self._last_request = time.monotonic()
        return response

    def search_documents(
        self,
        query: str,
        limit: int,
        *,
        timeout_seconds: float | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
    ) -> list[tuple[SearchHit, FetchedDocument | None]]:
        clean_query = "".join(c if c.isalnum() else " " for c in query).strip()
        if not clean_query:
            clean_query = "research"
            
        request_kwargs: dict[str, object] = {
            "params": {
                "search_query": f"all:{clean_query}",
                "start": 0,
                "max_results": min(max(limit, 1), 12),
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        }
        if timeout_seconds is not None:
            request_kwargs["timeout"] = timeout_seconds
        response = self._paced_get(**request_kwargs)
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            raise ProviderRateLimitError(
                "arXiv rate limit reached",
                retry_after_seconds=float(retry) if retry and retry.isdigit() else None,
            )
        if response.status_code >= 400:
            raise SearchProviderError(f"arXiv returned HTTP {response.status_code}")
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise SearchProviderError("arXiv returned invalid Atom XML") from exc

        results: list[tuple[SearchHit, FetchedDocument]] = []
        for rank, entry in enumerate(root.findall(f"{_ATOM}entry")[:limit], start=1):
            entry_url = (entry.findtext(f"{_ATOM}id") or "").strip()
            title = " ".join((entry.findtext(f"{_ATOM}title") or "Untitled preprint").split())
            summary = " ".join((entry.findtext(f"{_ATOM}summary") or "").split())
            if not entry_url or not summary:
                continue
            arxiv_id = entry_url.rsplit("/", 1)[-1]
            authors = [
                " ".join((node.findtext(f"{_ATOM}name") or "").split())
                for node in entry.findall(f"{_ATOM}author")
            ]
            authors = [name for name in authors if name]
            published_at = _parse_time(entry.findtext(f"{_ATOM}published"))
            updated_at = _parse_time(entry.findtext(f"{_ATOM}updated"))
            if published_at is not None:
                if published_after is not None and published_at < published_after:
                    continue
                if published_before is not None and published_at > published_before:
                    continue
            primary_category = ""
            primary = entry.find(f"{_ARXIV}primary_category")
            if primary is not None:
                primary_category = primary.attrib.get("term", "")
            comment = " ".join((entry.findtext(f"{_ARXIV}comment") or "").split())
            pdf_url = next(
                (
                    link.attrib.get("href", "")
                    for link in entry.findall(f"{_ATOM}link")
                    if link.attrib.get("type") == "application/pdf"
                ),
                "",
            )
            lines = [
                f"Title: {title}",
                f"arXiv: {arxiv_id}",
                f"Authors: {', '.join(authors) if authors else 'unknown'}",
                f"Primary category: {primary_category or 'unknown'}",
                f"Published: {published_at.isoformat() if published_at else 'unknown'}",
                f"Updated: {updated_at.isoformat() if updated_at else 'unknown'}",
            ]
            if comment:
                lines.append(f"Comment: {comment}")
            if pdf_url:
                lines.append(f"Permitted PDF URL: {pdf_url}")
            lines.extend(["", "Abstract", summary])
            text = "\n".join(lines)
            identifier = f"arxiv:{arxiv_id}"
            hit = SearchHit(
                title=title,
                url=entry_url,
                snippet=summary[:500],
                rank=rank,
                provider="arxiv",
                engine="arxiv-atom",
                source_kind="academic",
                canonical_identifier=identifier,
                published_at=published_at,
                full_text_url=pdf_url if pdf_url.startswith("http") else None,
                full_text_mime_type="application/pdf" if pdf_url.startswith("http") else None,
            )
            document = FetchedDocument(
                source_id=uuid4(),
                title=title,
                url=entry_url,
                final_url=entry_url,
                text=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                fetched_at=datetime.now(UTC),
                extraction_method="arxiv-metadata-abstract",
                mime_type="application/atom+xml",
                byte_count=len(text.encode("utf-8")),
                source_kind="academic",
                canonical_identifier=identifier,
                published_at=published_at,
            )
            results.append((hit, document))
        return results

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
