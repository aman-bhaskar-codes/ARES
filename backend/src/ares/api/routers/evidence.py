# ruff: noqa: F403, F405, E501
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
from ares.application.repository import NotFoundError
import logging
logger = logging.getLogger('ares.api')
router = APIRouter()

@router.get('/api/v1/evidence/{evidence_id}', response_model=EvidenceView)
def get_evidence(evidence_id: UUID, *, request: Request) -> EvidenceView:
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
        return repository.get_evidence(evidence_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc