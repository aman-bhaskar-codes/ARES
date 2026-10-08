from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from ares.adapters.safe_fetch import FetchError, UnsafeUrlError, validate_public_url
from ares.domain.models import FetchedDocument


class BrowserFetchError(FetchError):
    """Browser sidecar failed to produce a bounded public-document extraction."""


class BrowserFetcher:
    """Read-only client for the isolated browser-rendering sidecar.

    The research worker never launches Chromium itself. The target URL is validated before it
    crosses the sidecar boundary and the returned final URL is validated again before the result
    is admitted as evidence. The sidecar remains responsible for *network-level* isolation of
    navigation, redirects, subresources, DNS rebinding and WebSockets; application URL checks
    are defense in depth, not that isolation boundary.
    """

    def __init__(
        self,
        service_url: str,
        *,
        service_token: str,
        timeout_seconds: float = 20.0,
        max_text_chars: int = 150_000,
    ):
        parsed = urlparse(service_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("browser service URL must be an http(s) origin without credentials")
        token = service_token.strip()
        if len(token) < 32:
            raise ValueError("browser service token must be at least 32 characters")
        self.service_url = service_url.rstrip("/")
        self.service_token = token
        self.timeout_seconds = timeout_seconds
        self.max_text_chars = max_text_chars

    def fetch(self, url: str, *, timeout_seconds: float | None = None) -> FetchedDocument:
        # Blocks direct internal targets even if discovery/provider data is compromised.
        validate_public_url(url)
        deadline = (
            self.timeout_seconds
            if timeout_seconds is None
            else min(self.timeout_seconds, float(timeout_seconds))
        )
        try:
            response = httpx.post(
                f"{self.service_url}/v1/render",
                json={"url": url, "max_text_chars": self.max_text_chars},
                headers={"Authorization": f"Bearer {self.service_token}"},
                timeout=max(0.1, deadline),
                follow_redirects=False,
            )
            response.raise_for_status()
            payload: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BrowserFetchError("isolated browser renderer unavailable") from exc
        if not isinstance(payload, dict):
            raise BrowserFetchError("browser renderer returned an invalid response")
        final_url = payload.get("final_url")
        text = payload.get("text")
        if not isinstance(final_url, str) or not isinstance(text, str):
            raise BrowserFetchError("browser renderer response is missing final_url/text")
        validate_public_url(final_url)
        if len(text.strip()) < 120:
            raise BrowserFetchError("browser-rendered text is too short")
        if len(text) > self.max_text_chars:
            raise BrowserFetchError("browser renderer exceeded text limit")
        try:
            document = FetchedDocument.model_validate(
                {
                    "title": payload.get("title") or final_url,
                    "url": url,
                    "final_url": final_url,
                    "text": text,
                    "content_hash": payload["content_hash"],
                    "fetched_at": payload.get("fetched_at"),
                    "extraction_method": payload.get("extraction_method", "browser-rendered"),
                    "mime_type": payload.get("mime_type", "text/html"),
                    "byte_count": payload.get("byte_count", 0),
                    "source_kind": "web",
                    "published_at": payload.get("published_at"),
                }
            )
        except Exception as exc:
            raise BrowserFetchError(
                "browser renderer returned an invalid document contract"
            ) from exc
        return document


class BrowserFallbackFetcher:
    """Use safe direct HTTP first; invoke the isolated browser only for extraction failures.

    Unsafe URL failures are never retried through a browser. This keeps the browser a narrowly
    scoped rendering fallback rather than a second general-purpose network path.
    """

    def __init__(self, primary, browser: BrowserFetcher):
        self.primary = primary
        self.browser = browser

    def fetch(self, url: str, *, timeout_seconds: float | None = None) -> FetchedDocument:
        try:
            return self.primary.fetch(url, timeout_seconds=timeout_seconds)
        except UnsafeUrlError:
            raise
        except FetchError:
            document = self.browser.fetch(url, timeout_seconds=timeout_seconds)
            return document.model_copy(
                update={"extraction_method": f"browser-fallback:{document.extraction_method}"}
            )
