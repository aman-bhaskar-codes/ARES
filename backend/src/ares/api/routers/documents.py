# ruff: noqa: F403, F405, E501
from fastapi import APIRouter, Request
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
import logging
logger = logging.getLogger('ares.api')
router = APIRouter()

@router.get('/api/v1/documents', response_model=list[DocumentView])
def list_documents(*, request: Request) -> list[DocumentView]:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    return repository.list_documents()