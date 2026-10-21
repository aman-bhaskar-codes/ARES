"""Per-client token bucket / sliding window rate limiting middleware."""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Mapping
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


class SlidingWindowRateLimiter:
    """Sliding-window request rate limiter in seconds."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        *,
        rpm: int | None = None,
        window_seconds: float = 60.0,
    ) -> None:
        self.capacity = rpm if rpm is not None else requests_per_minute
        self.window_seconds = window_seconds
        self.history: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_key: str, now: float | None = None) -> tuple[bool, float]:
        current_time = now if now is not None else time.monotonic()
        timestamps = self.history[client_key]
        cutoff = current_time - self.window_seconds

        # Prune expired timestamps
        while timestamps and timestamps[0] <= cutoff:
            timestamps.pop(0)

        if len(timestamps) < self.capacity:
            timestamps.append(current_time)
            return True, 0.0

        oldest = timestamps[0]
        retry_after = max(1.0, self.window_seconds - (current_time - oldest))
        return False, retry_after


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce rate limits per client IP on sensitive mutating and compute endpoints."""

    PROTECTED_ROUTES: ClassVar[Mapping[str, str]] = {
        "/api/v1/runs": "runs",
        "/api/v1/documents": "upload",
        "/api/v2/assets": "upload",
        "/api/v2/ingestions": "upload",
    }

    def __init__(
        self,
        app: ASGIApp,
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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled or request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            res: Response = await call_next(request)
            return res

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

        default_res: Response = await call_next(request)
        return default_res
