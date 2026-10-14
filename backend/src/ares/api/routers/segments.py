from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from ares.api.dependencies import get_repository
from ares.application.repository import NotFoundError, Repository
from ares.domain.assets import SegmentView, TableView

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.get("/api/v2/segments/{segment_id}", response_model=SegmentView)
def get_segment(
    segment_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> SegmentView:
    try:
        return repository.get_segment(segment_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.get("/api/v2/segments/{segment_id}/table", response_model=TableView)
def get_segment_table(
    segment_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> TableView:
    try:
        return repository.get_table_for_segment(segment_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.get("/api/v2/tables/{table_id}", response_model=TableView)
def get_table(
    table_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> TableView:
    try:
        return repository.get_table(table_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
