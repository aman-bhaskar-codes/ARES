# ruff: noqa: F403, F405, E501
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException, Query
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
from ares.application.repository import NotFoundError
import logging
logger = logging.getLogger('ares.api')
router = APIRouter()

@router.get('/api/v2/ingestions', response_model=list[IngestionView])
def list_ingestions(limit: int=Query(default=100, ge=1, le=500), *, request: Request) -> list[IngestionView]:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    return repository.list_ingestions(limit=limit)

@router.get('/api/v2/ingestions/{ingestion_id}', response_model=IngestionView)
def get_ingestion(ingestion_id: UUID, *, request: Request) -> IngestionView:
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
        return repository.get_ingestion(ingestion_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc

@router.post('/api/v2/ingestions/{ingestion_id}/cancel', response_model=IngestionView, status_code=202)
def cancel_ingestion(ingestion_id: UUID, *, request: Request) -> IngestionView:
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
        return repository.request_ingestion_cancel(ingestion_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc

@router.post('/api/v2/ingestions/{ingestion_id}/retry', response_model=IngestionView, status_code=202)
def retry_ingestion(ingestion_id: UUID, *, request: Request) -> IngestionView:
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
        return repository.retry_ingestion(ingestion_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={'code': 'INGESTION_NOT_RETRYABLE', 'message': str(exc)}) from exc