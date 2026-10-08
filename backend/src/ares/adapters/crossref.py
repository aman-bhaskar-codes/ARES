from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from html import unescape
from uuid import uuid4

import httpx

from ares.application.providers import DiscoveryProvider, ProviderMetadata, ProviderCapabilities
from ares.domain.models import FetchedDocument, SearchHit
from ares.ports.errors import ProviderRateLimitError, SearchProviderError

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _plain(value: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", value))).strip()


def _date_from_parts(value) -> datetime | None:
    try:
        parts = value["date-parts"][0]
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return datetime(year, month, day, tzinfo=UTC)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class CrossrefAcademicProvider(DiscoveryProvider):
    """Crossref DOI metadata adapter using the public/polite REST API."""

    def __init__(
        self,
        *,
        mailto: str = "",
        base_url: str = "https://api.crossref.org",
        client: httpx.Client | None = None,
    ):
        self.mailto = mailto.strip()
        headers = {"User-Agent": "ARES-research/0.4 (+local research assistant)"}
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=20.0
        )
        self._owns_client = client is None

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="crossref",
            source_kind="academic",
            capabilities=ProviderCapabilities(
                supports_time_range=True,
                supports_full_text=False,
                supports_exact_id=True,
            ),
            cost_class="free",
            timeout_seconds=20.0,
            rate_limit_rpm=None,
            cache_ttl_seconds=604800,
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
        params: dict[str, str | int] = {
            "query.bibliographic": query,
            "rows": min(max(limit, 1), 20),
            "select": "DOI,title,author,container-title,published,published-online,published-print,abstract,type,URL,subject",
        }
        filters: list[str] = []
        if published_after is not None:
            filters.append(f"from-pub-date:{published_after.date().isoformat()}")
        if published_before is not None:
            filters.append(f"until-pub-date:{published_before.date().isoformat()}")
        if filters:
            params["filter"] = ",".join(filters)
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            response = (
                self._client.get("/works", params=params, timeout=timeout_seconds)
                if timeout_seconds is not None
                else self._client.get("/works", params=params)
            )
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"Crossref request failed: {type(exc).__name__}") from exc
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            raise ProviderRateLimitError(
                "Crossref rate limit reached",
                retry_after_seconds=float(retry) if retry and retry.isdigit() else None,
            )
        if response.status_code >= 400:
            raise SearchProviderError(f"Crossref returned HTTP {response.status_code}")
        try:
            items = response.json()["message"]["items"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SearchProviderError("Crossref returned an invalid response schema") from exc

        results: list[tuple[SearchHit, FetchedDocument]] = []
        for rank, item in enumerate(items[:limit], start=1):
            doi = str(item.get("DOI") or "").strip().lower()
            titles = item.get("title") or []
            title = str(titles[0] if titles else "Untitled work").strip()
            if not doi or not title:
                continue
            url = f"https://doi.org/{doi}"
            authors = []
            for author in (item.get("author") or [])[:20]:
                name = " ".join(
                    part for part in [author.get("given", ""), author.get("family", "")] if part
                ).strip()
                if name:
                    authors.append(name)
            containers = item.get("container-title") or []
            container = str(containers[0]) if containers else ""
            published_at = (
                _date_from_parts(item.get("published"))
                or _date_from_parts(item.get("published-online"))
                or _date_from_parts(item.get("published-print"))
            )
            abstract = _plain(str(item.get("abstract") or ""))
            subjects = ", ".join(str(value) for value in (item.get("subject") or [])[:12])
            lines = [
                f"Title: {title}",
                f"DOI: {doi}",
                f"Authors: {', '.join(authors) if authors else 'unknown'}",
                f"Container: {container or 'unknown'}",
                f"Published: {published_at.date().isoformat() if published_at else 'unknown'}",
                f"Type: {item.get('type') or 'unknown'}",
            ]
            if subjects:
                lines.append(f"Subjects: {subjects}")
            if abstract:
                lines.extend(["", "Abstract", abstract])
            text = "\n".join(lines)
            hit = SearchHit(
                title=title,
                url=url,
                snippet=(abstract or text)[:500],
                rank=rank,
                provider="crossref",
                engine="crossref-rest",
                source_kind="academic",
                canonical_identifier=f"doi:{doi}",
                published_at=published_at,
            )
            document = FetchedDocument(
                source_id=uuid4(),
                title=title,
                url=url,
                final_url=url,
                text=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                fetched_at=datetime.now(UTC),
                extraction_method="crossref-metadata" + ("-abstract" if abstract else ""),
                mime_type="application/vnd.crossref.work+json",
                byte_count=len(text.encode("utf-8")),
                source_kind="academic",
                canonical_identifier=f"doi:{doi}",
                published_at=published_at,
            )
            results.append((hit, document))
        return results

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
