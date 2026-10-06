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

@router.post('/api/v1/conversations', response_model=ConversationView, status_code=201)
def create_conversation(payload: ConversationCreate, *, request: Request) -> ConversationView:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    return repository.create_conversation(payload.title)

@router.get('/api/v1/conversations', response_model=list[ConversationView])
def list_conversations(*, request: Request) -> list[ConversationView]:
    repository = request.app.state.repository
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    return repository.list_conversations()

@router.get('/api/v1/conversations/{conversation_id}/runs', response_model=list[RunSnapshot])
def list_conversation_runs(conversation_id: UUID, *, request: Request) -> list[RunSnapshot]:
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
        return repository.list_runs_for_conversation(conversation_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': str(exc)}) from exc