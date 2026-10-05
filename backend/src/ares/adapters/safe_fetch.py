from __future__ import annotations

import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
from html import unescape
from urllib.parse import urljoin, urlparse

from ares.domain.models import FetchedDocument


class UnsafeUrlError(ValueError):
    pass


class FetchError(RuntimeError):
    pass


_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_CHARSET = re.compile(r"charset=([^;\s]+)", re.IGNORECASE)


def _resolve_public_target(hostname: str, port: int) -> str:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"DNS resolution failed for {hostname}") from exc
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise FetchError(f"DNS resolution returned no addresses for {hostname}")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeUrlError(f"non-public destination blocked: {ip}")
    return addresses[0]


def validate_public_url(url: str) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise UnsafeUrlError("control characters in URLs are blocked")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("only http(s) URLs are allowed")
    if not parsed.hostname:
        raise UnsafeUrlError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("userinfo in URLs is blocked")
    if parsed.port not in {None, 80, 443}:
        raise UnsafeUrlError("non-standard ports are blocked")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _resolve_public_target(parsed.hostname, port)
    return url


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, target_ip: str, port: int, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout)
        self._target_ip = target_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._target_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, target_ip: str, port: int, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout, context=ssl.create_default_context())
        self._target_ip = target_ip

    def connect(self) -> None:
        raw = socket.create_connection((self._target_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _extract_text(html: str) -> tuple[str, str, str]:
    title_match = _TITLE.search(html)
    title = _WS.sub(" ", unescape(title_match.group(1))).strip() if title_match else "Untitled source"
    try:
        import trafilatura  # type: ignore[import-not-found]

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        if extracted and len(extracted.strip()) >= 120:
            return title, extracted.strip(), "trafilatura"
    except ImportError:
        pass
    cleaned = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = _WS.sub(" ", unescape(_TAGS.sub(" ", cleaned))).strip()
    return title, text, "html-basic"


class SafeHttpFetcher:
    """Fetch public HTTP(S) content by connecting to a validated, pinned resolved IP.

    Pinning the connection target closes the DNS-rebinding gap left by validating a hostname
    and then allowing a separate HTTP client's resolver to choose a different address.
    """

    def __init__(self, timeout_seconds: float = 12.0, max_bytes: int = 2_000_000, max_redirects: int = 4):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    def _request(
        self, url: str, *, timeout_seconds: float | None = None, max_bytes: int | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        parsed = urlparse(url)
        validate_public_url(url)
        assert parsed.hostname is not None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        target_ip = _resolve_public_target(parsed.hostname, port)
        connection_cls = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        request_timeout = self.timeout_seconds if timeout_seconds is None else max(0.05, float(timeout_seconds))
        connection = connection_cls(parsed.hostname, target_ip, port, request_timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Host": parsed.hostname,
                    "User-Agent": "ARES/0.1 research client (+local development)",
                    "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            body_limit = self.max_bytes if max_bytes is None else max(1, int(max_bytes))
            body = response.read(body_limit + 1)
            headers = {key.lower(): value for key, value in response.getheaders()}
            return response.status, headers, body
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise FetchError(f"network fetch failed for {parsed.hostname}") from exc
        finally:
            connection.close()

    def _fetch_response(
        self, url: str, *, timeout_seconds: float | None = None, max_bytes: int | None = None
    ) -> tuple[str, dict[str, str], bytes]:
        current = url
        status_code = 0
        headers: dict[str, str] = {}
        body = b""
        byte_limit = self.max_bytes if max_bytes is None else max(1, int(max_bytes))
        for _ in range(self.max_redirects + 1):
            # Preserve the existing request call shape for the ordinary HTML/text
            # path.  A larger/smaller byte allowance is only passed when a caller
            # deliberately selects a different bounded profile (for example the
            # academic PDF path).  This keeps the public fetch behavior and its
            # security regression hooks stable while still allowing a separately
            # bounded rich-document read.
            if max_bytes is None:
                status_code, headers, body = self._request(
                    current, timeout_seconds=timeout_seconds
                )
            else:
                status_code, headers, body = self._request(
                    current, timeout_seconds=timeout_seconds, max_bytes=byte_limit
                )
            if status_code in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location:
                    raise FetchError("redirect without location")
                current = urljoin(current, location)
                continue
            break
        else:
            raise FetchError("too many redirects")
        if status_code >= 400:
            raise FetchError(f"source returned HTTP {status_code}")
        if len(body) > byte_limit:
            raise FetchError("source exceeds byte limit")
        return current, headers, body

    def fetch(self, url: str, *, timeout_seconds: float | None = None) -> FetchedDocument:
        current, headers, body = self._fetch_response(url, timeout_seconds=timeout_seconds)

        content_type = headers.get("content-type", "").lower()
        if "text/html" not in content_type and "text/plain" not in content_type:
            raise FetchError(f"unsupported content type: {content_type or 'unknown'}")
        charset_match = _CHARSET.search(content_type)
        charset = charset_match.group(1).strip('"\'') if charset_match else "utf-8"
        try:
            decoded = body.decode(charset, errors="replace")
        except LookupError:
            decoded = body.decode("utf-8", errors="replace")

        if "text/html" in content_type:
            title, text, method = _extract_text(decoded)
        else:
            title = urlparse(current).netloc
            text = decoded.strip()
            method = "text"
        if len(text) < 120:
            raise FetchError("extracted text is too short")
        stored_text = text[:150_000]
        return FetchedDocument(
            title=title,
            url=url,
            final_url=current,
            text=stored_text,
            content_hash=hashlib.sha256(stored_text.encode()).hexdigest(),
            extraction_method=method,
            mime_type=content_type.split(";", 1)[0] or "text/plain",
            byte_count=len(body),
        )

    def fetch_pdf(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
        max_bytes: int = 20 * 1024 * 1024,
        max_pages: int = 100,
        max_text_chars: int = 500_000,
    ) -> FetchedDocument:
        """Safely fetch and parse one public PDF with the existing M08 bounded parser.

        This path is intentionally separate from ordinary HTML fetching so an academic full-text
        candidate cannot silently raise the general web byte limit. Redirects are revalidated and
        IP-pinned on every hop before the untrusted PDF enters the parser subprocess.
        """
        current, headers, body = self._fetch_response(
            url, timeout_seconds=timeout_seconds, max_bytes=max_bytes
        )
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/pdf" and not body.startswith(b"%PDF-"):
            raise FetchError(f"academic full-text candidate is not a PDF: {content_type or 'unknown'}")
        try:
            from ares.adapters.pdf_parser import BoundedPdfParser, PdfParseError

            parser = BoundedPdfParser(
                max_bytes=max_bytes,
                max_pages=max_pages,
                max_text_chars=max_text_chars,
                timeout_seconds=max(2.0, min(float(timeout_seconds or self.timeout_seconds), 45.0)),
            )
            parsed = parser.parse(body)
        except PdfParseError as exc:
            raise FetchError(f"academic PDF parsing failed: {exc}") from exc
        if parsed.status == "needs_ocr" or len(parsed.text.strip()) < 120:
            raise FetchError("academic PDF has no usable text layer")
        stored_text = parsed.text[:max_text_chars]
        return FetchedDocument(
            title=urlparse(current).path.rsplit("/", 1)[-1] or urlparse(current).netloc,
            url=url,
            final_url=current,
            text=stored_text,
            content_hash=hashlib.sha256(stored_text.encode("utf-8")).hexdigest(),
            extraction_method=f"academic-pdf:{parsed.parser_version}",
            mime_type="application/pdf",
            byte_count=len(body),
            page_map=parsed.page_map,
        )
