from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from ares.adapters.browser_fetch import BrowserFetchError, BrowserFallbackFetcher, BrowserFetcher
from ares.adapters.safe_fetch import FetchError, UnsafeUrlError
from ares.domain.models import FetchedDocument


class _FailingPrimary:
    def fetch(self, url: str, *, timeout_seconds=None):
        raise FetchError("dynamic page")


class _UnsafePrimary:
    def fetch(self, url: str, *, timeout_seconds=None):
        raise UnsafeUrlError("blocked")


class _StubBrowser:
    def __init__(self): self.called = False
    def fetch(self, url: str, *, timeout_seconds=None):
        self.called = True
        text = "Rendered evidence " * 20
        return FetchedDocument(
            title="Rendered", url=url, final_url=url, text=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(), fetched_at=datetime.now(UTC),
            extraction_method="browser-rendered", mime_type="text/html", byte_count=len(text),
        )


def test_fallback_uses_browser_only_after_safe_fetch_failure():
    browser = _StubBrowser()
    result = BrowserFallbackFetcher(_FailingPrimary(), browser).fetch("https://example.com/article")
    assert browser.called is True
    assert result.extraction_method.startswith("browser-fallback:")


def test_fallback_never_routes_unsafe_url_to_browser():
    browser = _StubBrowser()
    with pytest.raises(UnsafeUrlError):
        BrowserFallbackFetcher(_UnsafePrimary(), browser).fetch("https://example.com")
    assert browser.called is False


def test_browser_client_rejects_invalid_sidecar_contract(monkeypatch):
    monkeypatch.setattr("ares.adapters.browser_fetch.validate_public_url", lambda value: value)

    class _Response:
        def raise_for_status(self): return None
        def json(self): return {"final_url": "https://example.com"}

    monkeypatch.setattr("ares.adapters.browser_fetch.httpx.post", lambda *args, **kwargs: _Response())
    with pytest.raises(BrowserFetchError):
        BrowserFetcher("http://browser:8090", service_token="x" * 32).fetch("https://example.com")


def test_browser_client_sends_service_bearer_token(monkeypatch):
    monkeypatch.setattr("ares.adapters.browser_fetch.validate_public_url", lambda value: value)
    captured = {}

    class _Response:
        def raise_for_status(self): return None
        def json(self):
            text = "rendered evidence " * 20
            return {
                "title": "Rendered", "final_url": "https://example.com", "text": text,
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                "fetched_at": datetime.now(UTC).isoformat(), "byte_count": len(text.encode()),
            }

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("ares.adapters.browser_fetch.httpx.post", fake_post)
    BrowserFetcher("http://browser:8090", service_token="s" * 40).fetch("https://example.com")
    assert captured["headers"]["Authorization"] == "Bearer " + "s" * 40


def test_browser_client_requires_strong_service_token():
    with pytest.raises(ValueError):
        BrowserFetcher("http://browser:8090", service_token="short")
