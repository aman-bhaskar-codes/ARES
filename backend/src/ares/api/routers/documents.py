from __future__ import annotations
from fastapi import Depends
import asyncio
import logging
from uuid import UUID
from pathlib import Path
from typing import Annotated
from fastapi import File, HTTPException, Request, Response, UploadFile
from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.adapters.pdf_parser import PdfParseError
from ares.api.dependencies import get_settings
from ares.api.settings import Settings
from ares.application.documents import DocumentIngestService
from ares.application.repository import NotFoundError, Repository
from ares.domain.models import DocumentTextCreate, DocumentView
from fastapi import APIRouter
from ares.api.dependencies import get_blobs
from ares.api.dependencies import get_documents
from ares.api.dependencies import get_repository

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.get("/api/v1/documents", response_model=list[DocumentView])
def list_documents(
    *, request: Request, repository: Repository = Depends(get_repository)
) -> list[DocumentView]:
    return repository.list_documents()


@router.post("/api/v1/documents/text", response_model=DocumentView, status_code=201)
async def create_text_document(
    payload: DocumentTextCreate, *, documents: DocumentIngestService = Depends(get_documents)
) -> DocumentView:
    return await asyncio.to_thread(documents.ingest_text, payload)


@router.post("/api/v1/documents/pdf", response_model=DocumentView, status_code=201)
async def create_pdf_document(
    file: Annotated[UploadFile, File(...)],
    *,
    cfg: Settings = Depends(get_settings),
    documents: DocumentIngestService = Depends(get_documents),
) -> DocumentView:
    name = Path(file.filename or "document.pdf").name.strip()[:255] or "document.pdf"
    if file.content_type not in {None, "", "application/pdf", "application/octet-stream"}:
        raise HTTPException(
            status_code=415,
            detail={
                "code": "UNSUPPORTED_MEDIA_TYPE",
                "message": "PDF upload must use application/pdf",
            },
        )
    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        received += len(chunk)
        if received > cfg.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "UPLOAD_TOO_LARGE",
                    "message": "PDF exceeds the configured upload limit",
                },
            )
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        return await asyncio.to_thread(documents.ingest_pdf, name=name, raw=raw)
    except PdfParseError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "PDF_PARSE_FAILED", "message": str(exc)}
        ) from exc


@router.delete("/api/v1/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    *,
    blobs: FilesystemBlobStore = Depends(get_blobs),
    repository: Repository = Depends(get_repository),
) -> Response:
    try:
        blob_keys = await asyncio.to_thread(repository.delete_document_with_blobs, document_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
    for blob_key in blob_keys:
        await asyncio.to_thread(blobs.delete, blob_key)
    return Response(status_code=204)
