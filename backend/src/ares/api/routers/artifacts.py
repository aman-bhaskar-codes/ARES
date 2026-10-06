# ruff: noqa: F403, F405, E501
from uuid import UUID
from fastapi import APIRouter, Request, Response, HTTPException
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
from ares.application.repository import NotFoundError
import asyncio
import logging
logger = logging.getLogger("ares.api")

router = APIRouter()

@router.get('/api/v1/artifacts/{artifact_id}')
async def download_artifact(artifact_id: UUID, *, request: Request) -> Response:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    blobs = request.app.state.blobs
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    try:
        record = await asyncio.to_thread(repository.get_artifact_record, artifact_id)
        content = await asyncio.to_thread(blobs.get_bytes, record.blob_key)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc
    return Response(content=content, media_type=record.mime_type, headers={'Content-Disposition': f'attachment; filename="{record.name}"'})
