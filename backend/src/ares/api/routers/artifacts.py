from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.api.dependencies import get_blobs, get_repository
from ares.api.downloads import content_disposition
from ares.application.repository import NotFoundError, Repository

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.get("/api/v1/artifacts/{artifact_id}")
async def download_artifact(
    artifact_id: UUID,
    *,
    blobs: FilesystemBlobStore = Depends(get_blobs),
    repository: Repository = Depends(get_repository),
) -> Response:
    try:
        record = await asyncio.to_thread(repository.get_artifact_record, artifact_id)
        path = await asyncio.to_thread(blobs.file_path, record.blob_key)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=410,
            detail={"code": "ARTIFACT_GONE", "message": "artifact bytes are unavailable"},
        ) from exc
    return FileResponse(
        path=path,
        media_type=record.content_type,
        headers={"Content-Disposition": content_disposition(record.file_name)},
    )
