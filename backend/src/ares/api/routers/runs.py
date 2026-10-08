# ruff: noqa: F403, F405, E501
from uuid import UUID
from fastapi import APIRouter, Request, Response, HTTPException, Header
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
from ares.application.repository import NotFoundError, IdempotencyConflictError, RunAdmissionError
from ares.application.visualizations import VisualizationExportError
import logging
logger = logging.getLogger('ares.api')
router = APIRouter()

@router.get('/api/v1/models')
def available_models(request: Request):
    cfg = request.app.state.settings
    return {
        "default": "qwen" if cfg.local_llm_enabled else "gemini",
        "models": [
            {"id": "gemini", "label": "Gemini", "model": cfg.gemini_model,
             "available": bool(cfg.gemini_api_key), "location": "cloud"},
            {"id": "qwen", "label": "Qwen", "model": cfg.local_llm_model,
             "available": cfg.local_llm_enabled, "location": "local"},
        ],
    }

@router.post('/api/v1/runs', response_model=RunSnapshot, status_code=202)
def create_run(payload: RunCreate, response: Response, idempotency_key: str=Header(..., alias='Idempotency-Key'), *, request: Request) -> RunSnapshot:
    repository = request.app.state.repository
    cfg = request.app.state.settings
    provider = payload.model_provider or ("qwen" if cfg.local_llm_enabled else "gemini")
    if cfg.ares_mode != "demo" and ((provider == "gemini" and not cfg.gemini_api_key) or
                                    (provider == "qwen" and not cfg.local_llm_enabled)):
        raise HTTPException(status_code=503, detail={"code": "MODEL_UNAVAILABLE", "message": f"{provider.title()} is not configured on this server."})
    payload = payload.model_copy(update={"model_provider": provider})
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    try:
        snapshot, created = repository.create_run(payload, idempotency_key=idempotency_key, max_active_runs=cfg.max_active_runs, max_active_runs_per_workspace=cfg.max_active_runs_per_workspace, max_active_runs_per_user=cfg.max_active_runs_per_user)
    except RunAdmissionError as exc:
        raise HTTPException(status_code=429, detail={'code': 'RUN_CAPACITY_REACHED', 'message': str(exc)}, headers={'Retry-After': '5'}) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT', 'message': str(exc)}) from exc
    if not created:
        response.headers['X-Idempotent-Replay'] = 'true'
    return snapshot

@router.get('/api/v1/runs/{run_id}', response_model=RunSnapshot)
def get_run(run_id: UUID, *, request: Request) -> RunSnapshot:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    try:
        return repository.get_run(run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc

@router.get('/api/v1/runs/{run_id}/evidence', response_model=list[EvidenceView])
def list_run_evidence(run_id: UUID, *, request: Request) -> list[EvidenceView]:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    try:
        return repository.list_run_evidence(run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc

@router.get('/api/v1/runs/{run_id}/quality', response_model=RunQualityView)
def get_run_quality(run_id: UUID, *, request: Request) -> RunQualityView:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    try:
        return repository.get_run_quality(run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc

@router.get('/api/v2/runs/{run_id}/visualizations', response_model=list[VisualizationView])
def get_run_visualizations(run_id: UUID, *, request: Request) -> list[VisualizationView]:
    cfg = request.app.state.settings
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    visualizations = getattr(request.app.state, 'visualizations', None)
    engine = getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    if not cfg.visualizations_enabled:
        return []
    if not visualization_storage_ready(cfg, engine):
        raise HTTPException(status_code=503, detail={'code': 'VISUALIZATIONS_NOT_READY', 'message': 'Visualization storage is not migrated or reachable.'})
    try:
        return visualizations.list_for_run(run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc

@router.get('/api/v2/runs/{run_id}/visualizations/{visualization_id}/export.csv', response_class=Response, responses={200: {'content': {'text/csv': {'schema': {'type': 'string'}}}, 'description': 'Lineage-bearing CSV export'}})
def export_run_visualization_csv(run_id: UUID, visualization_id: UUID, *, request: Request) -> Response:
    cfg = request.app.state.settings
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    visualizations = getattr(request.app.state, 'visualizations', None)
    engine = getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    if not cfg.visualizations_enabled:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'visualization not found'})
    if not visualization_storage_ready(cfg, engine):
        raise HTTPException(status_code=503, detail={'code': 'VISUALIZATIONS_NOT_READY', 'message': 'Visualization storage is not migrated or reachable.'})
    try:
        filename, content = visualizations.export_csv(run_id, visualization_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
    except VisualizationExportError as exc:
        raise HTTPException(status_code=409, detail={'code': 'VISUALIZATION_EXPORT_UNAVAILABLE', 'message': str(exc)}) from exc
    return Response(content=content, media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

@router.post('/api/v1/runs/{run_id}/cancel', response_model=RunSnapshot, status_code=202)
def cancel_run(run_id: UUID, *, request: Request) -> RunSnapshot:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    try:
        return repository.request_cancel(run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
