from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoryEpisode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    user_id: UUID
    conversation_id: UUID | None = None
    run_id: UUID | None = None
    title: str
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryFact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    user_id: UUID
    subject: str
    predicate: str
    fact: str
    evidence_source: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: Literal["active", "superseded", "contradiction"] = "active"
    superseded_by_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryPreference(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    user_id: UUID
    depth: Literal["quick", "standard", "deep"] = "standard"
    preferred_domains: list[str] = Field(default_factory=list)
    excluded_domains: list[str] = Field(default_factory=list)
    tone: Literal["academic", "brief", "technical", "general"] = "academic"
    custom_instructions: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EpisodeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)
    key_findings: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    conversation_id: UUID | None = None
    run_id: UUID | None = None


class FactCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    predicate: str = Field(min_length=1, max_length=100)
    fact: str = Field(min_length=1)
    evidence_source: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    superseded_by_id: UUID | None = None


class PreferenceUpdate(BaseModel):
    depth: Literal["quick", "standard", "deep"] | None = None
    preferred_domains: list[str] | None = None
    excluded_domains: list[str] | None = None
    tone: Literal["academic", "brief", "technical", "general"] | None = None
    custom_instructions: str | None = None


class MemorySearchResult(BaseModel):
    episodes: list[MemoryEpisode] = Field(default_factory=list)
    facts: list[MemoryFact] = Field(default_factory=list)
    relevance_scores: dict[str, float] = Field(default_factory=dict)
