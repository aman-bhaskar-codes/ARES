import socket

import pytest

from ares.adapters.safe_fetch import UnsafeUrlError, validate_public_url


def test_blocks_non_http_schemes() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_url("file:///etc/passwd")


def test_blocks_private_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_public_url("http://attacker.example")


def test_blocks_nonstandard_port() -> None:
    with pytest.raises(UnsafeUrlError, match="ports"):
        validate_public_url("https://example.com:8443/path")


def test_blocks_userinfo() -> None:
    with pytest.raises(UnsafeUrlError, match="userinfo"):
        validate_public_url("https://example.com@127.0.0.1/path")


def test_blocks_ipv6_loopback() -> None:
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_public_url("http://[::1]/metadata")


def test_blocks_link_local_metadata_address() -> None:
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_public_url("http://169.254.169.254/latest/meta-data/")


def test_rejects_mixed_public_and_private_dns_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443)),
        ],
    )
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_public_url("https://mixed.example/path")


def test_blocks_control_characters_before_parsing() -> None:
    with pytest.raises(UnsafeUrlError, match="control characters"):
        validate_public_url("https://example.com/path\nHost: 127.0.0.1")


def test_fetch_forwards_run_timeout_to_pinned_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from ares.adapters.safe_fetch import SafeHttpFetcher

    fetcher = SafeHttpFetcher(timeout_seconds=12.0)
    observed: list[float | None] = []

    def fake_request(url: str, *, timeout_seconds: float | None = None):
        observed.append(timeout_seconds)
        return 200, {"content-type": "text/plain; charset=utf-8"}, (b"evidence " * 20)

    monkeypatch.setattr(fetcher, "_request", fake_request)
    result = fetcher.fetch("https://example.com/source", timeout_seconds=1.2)
    assert observed == [1.2]
    assert "evidence" in result.text


def test_content_hash_matches_persisted_truncated_text(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    from ares.adapters.safe_fetch import SafeHttpFetcher

    fetcher = SafeHttpFetcher(timeout_seconds=2.0, max_bytes=1_000_000)
    long_text = ("0123456789" * 20_000).encode()

    def fake_request(url: str, *, timeout_seconds: float | None = None):
        del url, timeout_seconds
        return 200, {"content-type": "text/plain; charset=utf-8"}, long_text

    monkeypatch.setattr(fetcher, "_request", fake_request)
    result = fetcher.fetch("https://example.com/long")
    assert len(result.text) == 150_000
    assert result.content_hash == hashlib.sha256(result.text.encode()).hexdigest()
