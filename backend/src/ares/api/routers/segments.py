from typing import Annotated, Any
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response, HTTPException, Query, UploadFile, File, Header
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
from ares.application.auth import AuthenticationError
from ares.application.repository import NotFoundError, IdempotencyConflictError, RunAdmissionError
from ares.application.asset_ingestion import AssetAdmissionError
from ares.application.exports import ExportError
from ares.application.visualizations import VisualizationExportError
from ares.application.identity import Principal
import asyncio
import tempfile
import os
from pathlib import Path
import httpx
import logging
logger = logging.getLogger('ares.api')
router = APIRouter()

@router.get('/api/v2/segments/{segment_id}', response_model=SegmentView)
def get_segment(segment_id: UUID, *, request: Request) -> SegmentView:
    repository = request.app.state.repository
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    oidc = getattr(request.app.state, 'oidc', None)
    blobs = request.app.state.blobs
    asset_admission = getattr(request.app.state, 'asset_admission', None)
    documents = getattr(request.app.state, 'documents', None)
    exports = getattr(request.app.state, 'exports', None)
    visualizations = getattr(request.app.state, 'visualizations', None)
    engine = getattr(request.app.state, 'db_engine', None)
    local_media_runtime = getattr(request.app.state, 'local_media_runtime', None)
    try:
        return repository.get_segment(segment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc

@router.get('/api/v2/segments/{segment_id}/table', response_model=TableView)
def get_segment_table(segment_id: UUID, *, request: Request) -> TableView:
    repository = request.app.state.repository
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    oidc = getattr(request.app.state, 'oidc', None)
    blobs = request.app.state.blobs
    asset_admission = getattr(request.app.state, 'asset_admission', None)
    documents = getattr(request.app.state, 'documents', None)
    exports = getattr(request.app.state, 'exports', None)
    visualizations = getattr(request.app.state, 'visualizations', None)
    engine = getattr(request.app.state, 'db_engine', None)
    local_media_runtime = getattr(request.app.state, 'local_media_runtime', None)
    try:
        return repository.get_table_for_segment(segment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc

@router.get('/api/v2/tables/{table_id}', response_model=TableView)
def get_table(table_id: UUID, *, request: Request) -> TableView:
    repository = request.app.state.repository
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    oidc = getattr(request.app.state, 'oidc', None)
    blobs = request.app.state.blobs
    asset_admission = getattr(request.app.state, 'asset_admission', None)
    documents = getattr(request.app.state, 'documents', None)
    exports = getattr(request.app.state, 'exports', None)
    visualizations = getattr(request.app.state, 'visualizations', None)
    engine = getattr(request.app.state, 'db_engine', None)
    local_media_runtime = getattr(request.app.state, 'local_media_runtime', None)
    try:
        return repository.get_table(table_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc