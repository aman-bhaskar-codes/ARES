from __future__ import annotations
from fastapi import Depends
import logging
from uuid import UUID
from fastapi import HTTPException, Request
from ares.application.repository import NotFoundError, Repository
from fastapi import APIRouter
from ares.api.dependencies import get_repository
from ares.domain.models import EvidenceView

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.get("/api/v1/evidence/{evidence_id}", response_model=EvidenceView)
def get_evidence(
    evidence_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> EvidenceView:
    try:
        return repository.get_evidence(evidence_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
