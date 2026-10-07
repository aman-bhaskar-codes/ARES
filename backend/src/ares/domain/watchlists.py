from typing import Literal, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime, timezone

WatchlistState = Literal["active", "paused", "error", "completed"]

class WatchlistSchedule(BaseModel):
    interval_hours: int = Field(ge=6)
    timezone: str = "UTC"
    next_run_time: datetime
    missed_run_policy: Literal["coalesce"] = "coalesce"

class Watchlist(BaseModel):
    watchlist_id: UUID
    workspace_id: UUID
    owner_id: UUID
    name: str
    target_query: str
    tool_name: str
    schedule: WatchlistSchedule
    state: WatchlistState = "active"
    last_run_time: datetime | None = None
    last_run_status: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class EvidenceChange(BaseModel):
    change_id: UUID
    watchlist_id: UUID
    source_id: UUID
    change_type: Literal["metadata_only", "evidence_change", "new_source", "source_removed"]
    before_capture_date: datetime | None = None
    after_capture_date: datetime
    before_hash: str | None = None
    after_hash: str | None = None
    diff_summary: str | None = None
    assessed: bool = False
