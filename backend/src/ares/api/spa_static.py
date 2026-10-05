from __future__ import annotations

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SpaStaticFiles(StaticFiles):
    """Serve the built web app while preserving real 404s for APIs and assets.

    BrowserRouter deep links need ``index.html`` on a direct GET/HEAD navigation. We only
    fall back for HTML navigation requests whose path is outside reserved server namespaces
    and does not look like a concrete static asset. Unknown API routes therefore remain 404s.
    """

    _reserved_prefixes = ("api/", "health/", "metrics")

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            response = Response(status_code=404)
        if response.status_code != 404 or scope.get("method") not in {"GET", "HEAD"}:
            return response
        normalized = path.lstrip("/")
        if normalized.startswith(self._reserved_prefixes):
            return response
        if "." in normalized.rsplit("/", 1)[-1]:
            return response
        accept = Headers(scope=scope).get("accept", "")
        if "text/html" not in accept:
            return response
        return await super().get_response("index.html", scope)
