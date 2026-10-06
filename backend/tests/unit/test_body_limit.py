from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from ares.api.body_limit import PathAwareRequestBodyLimitMiddleware


async def _run_asgi(
    middleware: PathAwareRequestBodyLimitMiddleware,
    *,
    path: str,
    chunks: list[bytes],
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    queue = list(chunks)
    messages: list[dict[str, Any]] = []
    inner_called = False

    async def receive() -> dict[str, Any]:
        if queue:
            body = queue.pop(0)
            return {
                "type": "http.request",
                "body": body,
                "more_body": bool(queue),
            }
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    # Replace the inner app only for this invocation so the helper can report whether
    # the request actually crossed the middleware boundary.
    original_app = middleware.app

    async def app(
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        nonlocal inner_called
        inner_called = True
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware.app = app
    try:
        await middleware(scope, receive, send)
    finally:
        middleware.app = original_app
    return messages, inner_called


def _status(messages: list[dict[str, Any]]) -> int:
    return next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )


def _json_body(messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return json.loads(payload)


@pytest.mark.asyncio
async def test_body_limit_counts_streamed_bytes_without_content_length() -> None:
    middleware = PathAwareRequestBodyLimitMiddleware(
        lambda scope, receive, send: None,  # type: ignore[arg-type]
        default_max_body_size=8,
    )

    messages, inner_called = await _run_asgi(
        middleware,
        path="/api/v1/runs",
        chunks=[b"12345", b"6789"],
    )

    assert inner_called is True
    assert _status(messages) == 413
    assert _json_body(messages)["detail"]["code"] == "REQUEST_TOO_LARGE"


@pytest.mark.asyncio
async def test_asset_path_uses_larger_override() -> None:
    middleware = PathAwareRequestBodyLimitMiddleware(
        lambda scope, receive, send: None,  # type: ignore[arg-type]
        default_max_body_size=8,
        path_max_body_sizes={"/api/v2/assets": 16},
    )

    messages, inner_called = await _run_asgi(
        middleware,
        path="/api/v2/assets",
        chunks=[b"123456", b"7890"],
    )

    assert inner_called is True
    assert _status(messages) == 204


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [b"not-a-number", b"-1"])
async def test_invalid_content_length_is_rejected_before_application(value: bytes) -> None:
    middleware = PathAwareRequestBodyLimitMiddleware(
        lambda scope, receive, send: None,  # type: ignore[arg-type]
        default_max_body_size=8,
    )

    messages, inner_called = await _run_asgi(
        middleware,
        path="/api/v1/runs",
        chunks=[b""],
        headers=[(b"content-length", value)],
    )

    assert inner_called is False
    assert _status(messages) == 400
    assert _json_body(messages)["detail"]["code"] == "INVALID_CONTENT_LENGTH"
