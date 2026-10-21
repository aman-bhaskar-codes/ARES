"""Security headers middleware enforcing standard OWASP defense headers."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'self';"
)
API_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        csp: str = DEFAULT_CSP,
        api_csp: str = API_CSP,
        enable_hsts: bool = False,
    ) -> None:
        super().__init__(app)
        self.csp = csp
        self.api_csp = api_csp
        self.enable_hsts = enable_hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")

        path = request.url.path
        if path.startswith("/api/") or path.startswith("/health/"):
            response.headers.setdefault("Content-Security-Policy", self.api_csp)
        else:
            response.headers.setdefault("Content-Security-Policy", self.csp)

        if self.enable_hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
