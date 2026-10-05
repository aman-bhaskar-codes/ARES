from __future__ import annotations

from collections.abc import Mapping

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _RequestBodyTooLarge(Exception):
    pass


class PathAwareRequestBodyLimitMiddleware:
    """Bound raw HTTP request bodies before framework parsing.

    ARES keeps ordinary mutation requests small while allowing the dedicated asset
    upload endpoint a larger, separately configured multipart envelope. The wrapper
    counts actual ASGI body bytes, so missing or understated Content-Length headers do
    not bypass the limit.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_max_body_size: int,
        path_max_body_sizes: Mapping[str, int] | None = None,
    ) -> None:
        if default_max_body_size < 0:
            raise ValueError("default_max_body_size cannot be negative")
        overrides = dict(path_max_body_sizes or {})
        if any(limit < 0 for limit in overrides.values()):
            raise ValueError("path body-size limits cannot be negative")
        self.app = app
        self.default_max_body_size = default_max_body_size
        self.path_max_body_sizes = overrides

    @staticmethod
    def _json_error(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"detail": {"code": code, "message": message}},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_body_size = self.path_max_body_sizes.get(
            str(scope.get("path") or ""), self.default_max_body_size
        )
        raw_length = Headers(scope=scope).get("content-length")
        if raw_length is not None:
            try:
                declared_size = int(raw_length)
            except ValueError:
                response = self._json_error(
                    400, "INVALID_CONTENT_LENGTH", "invalid Content-Length header"
                )
                await response(scope, receive, send)
                return
            if declared_size < 0:
                response = self._json_error(
                    400, "INVALID_CONTENT_LENGTH", "invalid Content-Length header"
                )
                await response(scope, receive, send)
                return
            if declared_size > max_body_size:
                response = self._json_error(
                    413, "REQUEST_TOO_LARGE", "request body exceeds configured limit"
                )
                await response(scope, receive, send)
                return

        total_size = 0
        response_started = False

        async def receive_with_limit() -> Message:
            nonlocal total_size
            message = await receive()
            if message["type"] == "http.request":
                total_size += len(message.get("body", b""))
                if total_size > max_body_size:
                    raise _RequestBodyTooLarge
            return message

        async def send_tracking(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive_with_limit, send_tracking)
        except _RequestBodyTooLarge:
            # Request-parsing endpoints consume their body before starting a response.
            # If a future endpoint streams a response before consuming its request, a
            # second response would be invalid; surface that programming error instead.
            if response_started:
                raise
            response = self._json_error(
                413, "REQUEST_TOO_LARGE", "request body exceeds configured limit"
            )
            await response(scope, receive, send)
