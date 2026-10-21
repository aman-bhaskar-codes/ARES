from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse

from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.api.dependencies import get_asset_admission, get_blobs, get_repository, get_settings
from ares.api.downloads import content_disposition
from ares.api.settings import Settings
from ares.application.asset_ingestion import AssetAdmissionError, AssetAdmissionService
from ares.application.repository import NotFoundError, Repository
from ares.domain.assets import AssetAdmission, AssetView, MediaStoryboardView

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.get("/api/v2/assets/{asset_id}/storyboard", response_model=MediaStoryboardView)
@router.get(
    "/api/v2/assets/{asset_id}/timeline",
    response_model=MediaStoryboardView,
    include_in_schema=False,
)
def get_media_storyboard(
    asset_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> MediaStoryboardView:
    try:
        return repository.get_media_storyboard(asset_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.post("/api/v2/assets", response_model=AssetAdmission, status_code=202)
async def create_asset(
    file: Annotated[UploadFile, File(...)],
    *,
    asset_admission: AssetAdmissionService = Depends(get_asset_admission),
    cfg: Settings = Depends(get_settings),
) -> AssetAdmission:
    if not cfg.async_ingestion_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ASYNC_INGESTION_DISABLED",
                "message": "rich asset ingestion is disabled",
            },
        )
    name = Path(file.filename or "asset").name.strip()[:240] or "asset"
    supplied = file.content_type or "application/octet-stream"
    temporary_path: str | None = None
    received = 0
    try:
        with tempfile.NamedTemporaryFile(
            prefix="ares-upload-", suffix=".stage", delete=False
        ) as staged:
            temporary_path = staged.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                max_asset_bytes = max(
                    cfg.max_upload_bytes,
                    cfg.max_audio_bytes if cfg.audio_enabled else 0,
                    cfg.max_video_bytes if cfg.video_enabled else 0,
                )
                if received > max_asset_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "code": "UPLOAD_TOO_LARGE",
                            "message": "asset exceeds the configured upload limit",
                        },
                    )
                staged.write(chunk)
            staged.flush()
            os.fsync(staged.fileno())
        try:
            return await asyncio.to_thread(
                asset_admission.admit_staged,
                path=Path(temporary_path),
                name=name,
                supplied_mime=supplied,
            )
        except AssetAdmissionError as exc:
            message = str(exc)
            status = 415 if "unsupported file type" in message or "signature" in message else 422
            raise HTTPException(
                status_code=status, detail={"code": "ASSET_ADMISSION_REJECTED", "message": message}
            ) from exc
    finally:
        if temporary_path:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except OSError:
                logger.exception("failed to remove staged upload")


@router.delete("/api/v2/assets/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: UUID,
    *,
    blobs: FilesystemBlobStore = Depends(get_blobs),
    repository: Repository = Depends(get_repository),
) -> Response:
    try:
        blob_keys = await asyncio.to_thread(repository.delete_asset_with_blobs, asset_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    for blob_key in blob_keys:
        await asyncio.to_thread(blobs.delete, blob_key)
    return Response(status_code=204)


@router.get("/api/v2/assets/{asset_id}/content")
async def get_asset_content(
    asset_id: UUID,
    range_header: str | None = Header(default=None, alias="Range"),
    *,
    blobs: FilesystemBlobStore = Depends(get_blobs),
    repository: Repository = Depends(get_repository),
) -> Response:
    try:
        asset = await asyncio.to_thread(repository.get_asset_record, asset_id)
        size = await asyncio.to_thread(blobs.get_size, asset.original_blob_key)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=410, detail={"code": "ASSET_GONE", "message": "asset bytes are unavailable"}
        ) from exc
    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": content_disposition(asset.original_name, inline=True),
        "Cache-Control": "private, no-store",
    }
    if not range_header:
        path = await asyncio.to_thread(blobs.file_path, asset.original_blob_key)
        return FileResponse(
            path=path,
            media_type=asset.mime_type,
            headers={**base_headers, "Content-Length": str(size)},
        )
    match = re.fullmatch("bytes=(\\d*)-(\\d*)", range_header.strip())
    if not match or "," in range_header:
        raise HTTPException(
            status_code=416,
            detail={"code": "INVALID_RANGE", "message": "only one byte range is supported"},
        )
    left, right = match.groups()
    if not left and (not right):
        raise HTTPException(
            status_code=416, detail={"code": "INVALID_RANGE", "message": "invalid byte range"}
        )
    if left:
        start = int(left)
        end = min(size - 1, int(right) if right else size - 1)
    else:
        suffix = int(right)
        if suffix <= 0:
            raise HTTPException(
                status_code=416, detail={"code": "INVALID_RANGE", "message": "invalid suffix range"}
            )
        start = max(0, size - suffix)
        end = size - 1
    if start >= size or end < start:
        return Response(
            status_code=416, headers={**base_headers, "Content-Range": f"bytes */{size}"}
        )
    return StreamingResponse(
        content=blobs.iter_bytes(asset.original_blob_key, start=start, end_inclusive=end),
        status_code=206,
        media_type=asset.mime_type,
        headers={
            **base_headers,
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(end - start + 1),
        },
    )


@router.get("/api/v2/renditions/{rendition_id}/content")
async def get_rendition_content(
    rendition_id: UUID,
    *,
    blobs: FilesystemBlobStore = Depends(get_blobs),
    repository: Repository = Depends(get_repository),
) -> Response:
    try:
        rendition = await asyncio.to_thread(repository.get_rendition_record, rendition_id)
        path = await asyncio.to_thread(blobs.file_path, rendition.blob_key)
        size = await asyncio.to_thread(blobs.get_size, rendition.blob_key)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=410,
            detail={"code": "RENDITION_GONE", "message": "rendition bytes are unavailable"},
        ) from exc
    return FileResponse(
        path=path,
        media_type=rendition.mime_type,
        headers={
            "Content-Length": str(size),
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline",
        },
    )


@router.get("/api/v2/assets", response_model=list[AssetView])
def list_assets(limit: int = Query(default=100, ge=1, le=500), *, repository: Repository = Depends(get_repository)) -> list[AssetView]:
    return repository.list_assets(limit=limit)
