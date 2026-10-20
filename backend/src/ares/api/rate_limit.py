"""In-memory sliding-window rate limiter for write, upload, and run-creation endpoints."""
from __future__ import annotations

import time
from collections import defaultdict
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self, rpm: int, window_seconds: float = 60.0) -> None:
        self.rpm = rpm
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_id: str, now: float | None = None) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        if now is None:
            now = time.monotonic()
        cutoff = now - self.window_seconds
        timestamps = self._requests[client_id]
        while timestamps and timestamps[0] <= cutoff:
            timestamps.pop(0)

        if len(timestamps) >= self.rpm:
            retry_after = max(1.0, (timestamps[0] + self.window_seconds) - now)
            return False, retry_after

        timestamps.append(now)
        return True, 0.0

    def cleanup(self, max_idle_seconds: float = 300.0) -> None:
        """Prune client entries with no recent requests."""
        now = time.monotonic()
        cutoff = now - max_idle_seconds
        idle_clients = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in idle_clients:
            del self._requests[k]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Protects mutation, upload, and run-creation endpoints against abuse."""

    PROTECTED_ROUTES: ClassVar[dict[str, str]] = {
        "/api/v1/runs": "runs",
        "/api/v1/documents": "upload",
        "/api/v2/assets": "upload",
        "/api/v2/ingestions": "upload",
    }

    def __init__(
        self,
        app,
        *,
        enabled: bool = True,
        runs_rpm: int = 20,
        upload_rpm: int = 30,
        write_rpm: int = 60,
    ) -> None:
        super().__init__(app)
        self.enabled = enabled
        self._limiters = {
            "runs": SlidingWindowRateLimiter(runs_rpm),
            "upload": SlidingWindowRateLimiter(upload_rpm),
            "write": SlidingWindowRateLimiter(write_rpm),
        }

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)

        path = request.url.path
        category = None
        for prefix, cat in self.PROTECTED_ROUTES.items():
            if path == prefix or path.startswith(f"{prefix}/"):
                category = cat
                break

        if category is None and path.startswith("/api/"):
            category = "write"

        if category:
            client_ip = self._client_ip(request)
            limiter = self._limiters[category]
            allowed, retry_after = limiter.is_allowed(f"{category}:{client_ip}")
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": f"rate limit exceeded for {category} endpoints",
                        }
                    },
                    headers={"Retry-After": str(int(retry_after))},
                )

        return await call_next(request)
