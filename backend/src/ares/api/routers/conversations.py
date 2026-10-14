from __future__ import annotations
from fastapi import Depends
import logging
from uuid import UUID
from fastapi import HTTPException, Request
from ares.application.repository import NotFoundError, Repository
from fastapi import APIRouter
from ares.api.dependencies import get_repository
from ares.domain.models import ConversationCreate, ConversationView, RunSnapshot

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.post("/api/v1/conversations", response_model=ConversationView, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> ConversationView:
    return repository.create_conversation(payload.title)


@router.get("/api/v1/conversations", response_model=list[ConversationView])
def list_conversations(
    *, request: Request, repository: Repository = Depends(get_repository)
) -> list[ConversationView]:
    return repository.list_conversations()


@router.get("/api/v1/conversations/{conversation_id}/runs", response_model=list[RunSnapshot])
def list_conversation_runs(
    conversation_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)
) -> list[RunSnapshot]:
    try:
        return repository.list_runs_for_conversation(conversation_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc


@router.delete("/api/v1/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, *, request: Request, repository: Repository = Depends(get_repository)) -> None:
    try:
        repository.delete_conversation(conversation_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        ) from exc
