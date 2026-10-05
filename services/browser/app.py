from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import os
import socket
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# Playwright is intentionally a sidecar-only dependency. The main ARES API/worker does not
# import or launch a browser process.
try:
    from playwright.async_api import Browser, Route, async_playwright
except ImportError:  # pragma: no cover - exercised by container startup, not core unit tests.
    Browser = object  # type: ignore[assignment,misc]
    Route = object  # type: ignore[assignment,misc]
    async_playwright = None


class RenderRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)
    max_text_chars: int = Field(default=150_000, ge=120, le=150_000)


class RenderResponse(BaseModel):
    title: str
    final_url: str
    text: str
    content_hash: str
    fetched_at: datetime
    extraction_method: str = "playwright-dom-text-v1"
    mime_type: str = "text/html"
    byte_count: int


def public_addresses(url: str) -> tuple[str, ...]:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValueError("control characters are blocked")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only public http(s) URLs are permitted")
    if parsed.username or parsed.password:
        raise ValueError("URL userinfo is blocked")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("non-standard target ports are blocked")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("target DNS resolution failed") from exc
    addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise ValueError("target DNS resolution returned no addresses")
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("non-public target address blocked")
    return addresses


def validate_public_url(url: str) -> str:
    public_addresses(url)
    return url


class BrowserRuntime:
    def __init__(self) -> None:
        self._playwright = None
        self.browser: Browser | None = None
        self.slot = asyncio.Semaphore(1)

    async def start(self) -> None:
        if async_playwright is None:
            raise RuntimeError("playwright sidecar dependency is not installed")
        self._playwright = await async_playwright().start()
        # Never add --no-sandbox here. The container must run as a non-root user with a
        # Chromium-compatible seccomp profile, matching upstream Playwright guidance.
        self.browser = await self._playwright.chromium.launch(headless=True)

    async def close(self) -> None:
        if self.browser is not None:
            await self.browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def render(self, request: RenderRequest) -> RenderResponse:
        validate_public_url(request.url)
        if self.browser is None:
            raise RuntimeError("browser runtime is not ready")
        async with self.slot:
            context = await self.browser.new_context(
                accept_downloads=False,
                service_workers="block",
                ignore_https_errors=False,
            )
            page = await context.new_page()

            async def guard(route: Route) -> None:
                req = route.request
                if req.method.upper() not in {"GET", "HEAD"}:
                    await route.abort("blockedbyclient")
                    return
                try:
                    validate_public_url(req.url)
                except ValueError:
                    await route.abort("blockedbyclient")
                    return
                await route.continue_()

            await page.route("**/*", guard)
            # A rendered page does not need a bidirectional socket to extract readable text.
            # Blocking it also prevents a separate network channel from bypassing HTTP routing.
            route_ws = getattr(page, "route_web_socket", None)
            if callable(route_ws):
                await route_ws("**/*", lambda ws: ws.close())
            try:
                await page.goto(request.url, wait_until="domcontentloaded", timeout=12_000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=2_000)
                except Exception:
                    pass
                final_url = page.url
                validate_public_url(final_url)
                title = (await page.title()).strip()[:500] or final_url
                text = " ".join((await page.locator("body").inner_text(timeout=3_000)).split())
                if len(text) < 120:
                    raise ValueError("rendered body text is too short")
                text = text[: request.max_text_chars]
                encoded = text.encode("utf-8")
                return RenderResponse(
                    title=title,
                    final_url=final_url,
                    text=text,
                    content_hash=hashlib.sha256(encoded).hexdigest(),
                    fetched_at=datetime.now(UTC),
                    byte_count=len(encoded),
                )
            finally:
                await context.close()


runtime = BrowserRuntime()


def _configured_service_token() -> str:
    token = os.getenv("ARES_BROWSER_SERVICE_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("ARES_BROWSER_SERVICE_TOKEN must be at least 32 characters")
    return token


def _require_authorization(authorization: str | None) -> None:
    token = _configured_service_token()
    expected = f"Bearer {token}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _configured_service_token()
    await runtime.start()
    try:
        yield
    finally:
        await runtime.close()


app = FastAPI(title="ARES isolated browser renderer", version="0.10.0", lifespan=lifespan)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready() -> dict[str, str]:
    if runtime.browser is None:
        raise HTTPException(status_code=503, detail="browser not ready")
    return {"status": "ready"}


@app.post("/v1/render", response_model=RenderResponse)
async def render(request: RenderRequest, authorization: str | None = Header(default=None)) -> RenderResponse:
    _require_authorization(authorization)
    try:
        return await asyncio.wait_for(runtime.render(request), timeout=18.0)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="render deadline exceeded") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"browser render failed: {type(exc).__name__}") from exc
