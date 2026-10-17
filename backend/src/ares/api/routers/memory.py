from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ares.api.dependencies import get_repository
from ares.application.identity import Principal, current_principal, local_principal
from ares.application.repository import Repository
from ares.domain.memory import (
    EpisodeCreate,
    FactCreate,
    MemoryEpisode,
    MemoryFact,
    MemoryPreference,
    PreferenceUpdate,
)

logger = logging.getLogger("ares.api.memory")
router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


def _get_principal() -> Principal:
    return current_principal() or local_principal()


class ScoredEpisode(BaseModel):
    episode: MemoryEpisode
    score: float


class ScoredFact(BaseModel):
    fact: MemoryFact
    score: float


class SupersedeRequest(BaseModel):
    superseded_by_id: UUID


# --- Episodes ---


@router.get("/episodes", response_model=list[MemoryEpisode])
def list_episodes(
    limit: int = Query(default=50, ge=1, le=200),
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> list[MemoryEpisode]:
    principal = _get_principal()
    return repository.list_memory_episodes(principal.workspace_id, limit=limit)


@router.post("/episodes", response_model=MemoryEpisode, status_code=201)
def create_episode(
    payload: EpisodeCreate,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> MemoryEpisode:
    principal = _get_principal()
    return repository.create_memory_episode(principal.workspace_id, principal.user_id, payload)


@router.get("/episodes/search", response_model=list[ScoredEpisode])
def search_episodes(
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    half_life_days: float = Query(default=14.0, ge=0.1, le=365.0),
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> list[ScoredEpisode]:
    principal = _get_principal()
    results = repository.search_memory_episodes(
        principal.workspace_id, q, limit=limit, half_life_days=half_life_days
    )
    return [ScoredEpisode(episode=ep, score=score) for ep, score in results]


@router.get("/episodes/{episode_id}", response_model=MemoryEpisode)
def get_episode(
    episode_id: UUID,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> MemoryEpisode:
    principal = _get_principal()
    ep = repository.get_memory_episode(episode_id, principal.workspace_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="Memory episode not found")
    return ep


@router.delete("/episodes/{episode_id}", status_code=204)
def delete_episode(
    episode_id: UUID,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> None:
    principal = _get_principal()
    if not repository.delete_memory_episode(episode_id, principal.workspace_id):
        raise HTTPException(status_code=404, detail="Memory episode not found")


# --- Facts ---


@router.get("/facts", response_model=list[MemoryFact])
def list_facts(
    subject: str | None = Query(default=None),
    status: str = Query(default="active"),
    limit: int = Query(default=100, ge=1, le=500),
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> list[MemoryFact]:
    principal = _get_principal()
    return repository.list_memory_facts(
        principal.workspace_id, subject=subject, status=status, limit=limit
    )


@router.post("/facts", response_model=MemoryFact, status_code=201)
def create_fact(
    payload: FactCreate,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> MemoryFact:
    principal = _get_principal()
    return repository.create_memory_fact(principal.workspace_id, principal.user_id, payload)


@router.get("/facts/search", response_model=list[ScoredFact])
def search_facts(
    q: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> list[ScoredFact]:
    principal = _get_principal()
    results = repository.search_memory_facts(principal.workspace_id, q, limit=limit)
    return [ScoredFact(fact=fact, score=score) for fact, score in results]


@router.get("/facts/{fact_id}", response_model=MemoryFact)
def get_fact(
    fact_id: UUID,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> MemoryFact:
    principal = _get_principal()
    fact = repository.get_memory_fact(fact_id, principal.workspace_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Memory fact not found")
    return fact


@router.delete("/facts/{fact_id}", status_code=204)
def delete_fact(
    fact_id: UUID,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> None:
    principal = _get_principal()
    if not repository.delete_memory_fact(fact_id, principal.workspace_id):
        raise HTTPException(status_code=404, detail="Memory fact not found")


@router.post("/facts/{fact_id}/supersede")
def supersede_fact(
    fact_id: UUID,
    payload: SupersedeRequest,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict[str, str]:
    principal = _get_principal()
    success = repository.supersede_memory_fact(
        fact_id, payload.superseded_by_id, principal.workspace_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Fact not found or could not be superseded")
    return {"status": "superseded"}


@router.post("/facts/consolidate")
def consolidate_facts(
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict[str, int]:
    principal = _get_principal()
    return repository.consolidate_memory_facts(principal.workspace_id)


# --- Preferences ---


@router.get("/preferences", response_model=MemoryPreference)
def get_preferences(
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> MemoryPreference:
    principal = _get_principal()
    return repository.get_memory_preferences(principal.workspace_id, principal.user_id)


@router.put("/preferences", response_model=MemoryPreference)
def update_preferences(
    payload: PreferenceUpdate,
    *,
    request: Request,
    repository: Repository = Depends(get_repository),
) -> MemoryPreference:
    principal = _get_principal()
    return repository.update_memory_preferences(
        principal.workspace_id, principal.user_id, payload
    )
