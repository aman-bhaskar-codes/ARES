from __future__ import annotations
from fastapi import Depends
import logging
from uuid import UUID
from fastapi import HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from ares.api.dependencies import get_settings
from ares.api.settings import Settings
from ares.api.ingestion_stream import stream_ingestion_events
from ares.application.auth import AuthStore
from ares.application.identity import Principal
from ares.application.repository import NotFoundError, Repository
from fastapi import APIRouter
from ares.api.dependencies import get_auth_store
from ares.api.dependencies import get_repository
from ares.domain.assets import IngestionView

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.get("/api/v2/ingestions", response_model=list[IngestionView])
def list_ingestions(
    limit: int = Query(default=100, ge=1, le=500),
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> list[IngestionView]:
    return repository.list_ingestions(limit=limit)


@router.get("/api/v2/ingestions/{ingestion_id}", response_model=IngestionView)
def get_ingestion(
    ingestion_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> IngestionView:
    try:
        return repository.get_ingestion(ingestion_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.post(
    "/api/v2/ingestions/{ingestion_id}/cancel", response_model=IngestionView, status_code=202
)
def cancel_ingestion(
    ingestion_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> IngestionView:
    try:
        return repository.request_ingestion_cancel(ingestion_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.post(
    "/api/v2/ingestions/{ingestion_id}/retry", response_model=IngestionView, status_code=202
)
def retry_ingestion(
    ingestion_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> IngestionView:
    try:
        return repository.retry_ingestion(ingestion_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "INGESTION_NOT_RETRYABLE", "message": str(exc)}
        ) from exc


@router.get("/api/v2/ingestions/{ingestion_id}/events")
async def ingestion_events(
    ingestion_id: UUID,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    *,
    auth_store: AuthStore = Depends(get_auth_store),
    cfg: Settings = Depends(get_settings),
    repository: Repository = Depends(get_repository),
) -> StreamingResponse:
    try:
        repository.get_ingestion(ingestion_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    header = request.headers.get("last-event-id")
    try:
        header_cursor = max(0, int(header)) if header else 0
    except ValueError:
        header_cursor = 0
    cursor = max(header_cursor, after or 0)
    principal: Principal | None = request.state.principal
    session_token = request.cookies.get(cfg.session_cookie_name, "")

    def revalidate_ingestion() -> bool:
        if cfg.auth_mode == "disabled":
            return True
        if principal is None or not session_token:
            return False
        resolved = auth_store.resolve_session(session_token)
        return bool(
            resolved is not None
            and resolved.principal.session_id == principal.session_id
            and (resolved.principal.user_id == principal.user_id)
            and (resolved.principal.workspace_id == principal.workspace_id)
        )

    generator = stream_ingestion_events(
        repository=repository,
        ingestion_id=ingestion_id,
        request=request,
        principal=principal,
        after=cursor,
        revalidate=revalidate_ingestion,
        page_size=cfg.event_page_size,
        max_replay=cfg.event_max_replay,
        heartbeat_seconds=cfg.event_heartbeat_seconds,
        authorization_recheck_seconds=cfg.stream_authorization_recheck_seconds,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
