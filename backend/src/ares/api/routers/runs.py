from __future__ import annotations
from fastapi import Depends
from sqlalchemy import Engine
from ares.api.stream_authorization import stream_revalidator
import asyncio
import logging
from uuid import UUID
from fastapi import Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from ares.api.dependencies import get_settings
from ares.api.settings import Settings
from ares.api.event_stream import stream_run_events
from ares.application.auth import AuthStore
from ares.application.identity import Principal
from ares.application.exports import ExportError, ExportService
from ares.application.visualizations import VisualizationService
from ares.application.repository import NotFoundError, Repository
from ares.domain.models import ArtifactView, ExportCreate
from fastapi import APIRouter
from ares.api.dependencies import get_auth_store
from ares.api.dependencies import get_db_engine
from ares.api.dependencies import get_exports
from ares.api.dependencies import get_repository
from ares.api.dependencies import get_visualizations
from ares.api.dependencies import visualization_storage_ready
from ares.domain.models import EvidenceView, RunCreate, RunQualityView, RunSnapshot
from ares.domain.visualizations import VisualizationView
from ares.application.repository import IdempotencyConflictError, RunAdmissionError
from ares.application.visualizations import VisualizationExportError

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.get("/api/v1/models")
def available_models(request: Request, *, cfg: Settings = Depends(get_settings)):
    return {
        "default": "qwen" if cfg.local_llm_enabled else "gemini",
        "models": [
            {
                "id": "gemini",
                "label": "Gemini",
                "model": cfg.gemini_model,
                "available": bool(cfg.gemini_api_key),
                "location": "cloud",
            },
            {
                "id": "qwen",
                "label": "Qwen",
                "model": cfg.local_llm_model,
                "available": cfg.local_llm_enabled,
                "location": "local",
            },
        ],
    }


@router.post("/api/v1/runs", response_model=RunSnapshot, status_code=202)
def create_run(
    payload: RunCreate,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    *,
    request: Request,
    cfg: Settings = Depends(get_settings),
    repository: Repository = Depends(get_repository),
) -> RunSnapshot:
    provider = payload.model_provider or ("qwen" if cfg.local_llm_enabled else "gemini")
    if cfg.ares_mode != "demo" and (
        provider == "gemini"
        and (not cfg.gemini_api_key)
        or (provider == "qwen" and (not cfg.local_llm_enabled))
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "MODEL_UNAVAILABLE",
                "message": f"{provider.title()} is not configured on this server.",
            },
        )
    payload = payload.model_copy(update={"model_provider": provider})
    try:
        snapshot, created = repository.create_run(
            payload,
            idempotency_key=idempotency_key,
            max_active_runs=cfg.max_active_runs,
            max_active_runs_per_workspace=cfg.max_active_runs_per_workspace,
            max_active_runs_per_user=cfg.max_active_runs_per_user,
        )
    except RunAdmissionError as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "RUN_CAPACITY_REACHED", "message": str(exc)},
            headers={"Retry-After": "5"},
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)}
        ) from exc
    if not created:
        response.headers["X-Idempotent-Replay"] = "true"
    return snapshot


@router.get("/api/v1/runs/{run_id}", response_model=RunSnapshot)
def get_run(
    run_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> RunSnapshot:
    try:
        return repository.get_run(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.get("/api/v1/runs/{run_id}/evidence", response_model=list[EvidenceView])
def list_run_evidence(
    run_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> list[EvidenceView]:
    try:
        return repository.list_run_evidence(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.get("/api/v1/runs/{run_id}/quality", response_model=RunQualityView)
def get_run_quality(
    run_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> RunQualityView:
    try:
        return repository.get_run_quality(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.get("/api/v2/runs/{run_id}/visualizations", response_model=list[VisualizationView])
def get_run_visualizations(
    run_id: UUID,
    *,
    request: Request,
    cfg: Settings = Depends(get_settings),
    engine: Engine = Depends(get_db_engine),
    visualizations: VisualizationService = Depends(get_visualizations),
) -> list[VisualizationView]:
    if not cfg.visualizations_enabled:
        return []
    if not visualization_storage_ready(cfg, engine):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "VISUALIZATIONS_NOT_READY",
                "message": "Visualization storage is not migrated or reachable.",
            },
        )
    try:
        return visualizations.list_for_run(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.get(
    "/api/v2/runs/{run_id}/visualizations/{visualization_id}/export.csv",
    response_class=Response,
    responses={
        200: {
            "content": {"text/csv": {"schema": {"type": "string"}}},
            "description": "Lineage-bearing CSV export",
        }
    },
)
def export_run_visualization_csv(
    run_id: UUID,
    visualization_id: UUID,
    *,
    request: Request,
    cfg: Settings = Depends(get_settings),
    engine: Engine = Depends(get_db_engine),
    visualizations: VisualizationService = Depends(get_visualizations),
) -> Response:
    if not cfg.visualizations_enabled:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "visualization not found"}
        )
    if not visualization_storage_ready(cfg, engine):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "VISUALIZATIONS_NOT_READY",
                "message": "Visualization storage is not migrated or reachable.",
            },
        )
    try:
        filename, content = visualizations.export_csv(run_id, visualization_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    except VisualizationExportError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "VISUALIZATION_EXPORT_UNAVAILABLE", "message": str(exc)},
        ) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/api/v1/runs/{run_id}/cancel", response_model=RunSnapshot, status_code=202)
def cancel_run(
    run_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> RunSnapshot:
    try:
        return repository.request_cancel(run_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.post("/api/v1/runs/{run_id}/exports", response_model=ArtifactView, status_code=201)
async def create_export(
    run_id: UUID, payload: ExportCreate, *, exports: ExportService = Depends(get_exports)
) -> ArtifactView:
    try:
        return await asyncio.to_thread(exports.create, run_id, payload)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    except ExportError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "EXPORT_NOT_READY", "message": str(exc)}
        ) from exc


@router.get("/api/v1/runs/{run_id}/events")
async def events(
    run_id: UUID,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    *,
    auth_store: AuthStore = Depends(get_auth_store),
    cfg: Settings = Depends(get_settings),
    repository: Repository = Depends(get_repository),
) -> StreamingResponse:
    try:
        repository.get_run(run_id)
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
    revalidate = stream_revalidator(cfg, auth_store, principal, session_token)
    generator = stream_run_events(
        repository=repository,
        run_id=run_id,
        request=request,
        principal=principal,
        after=cursor,
        revalidate=revalidate,
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
