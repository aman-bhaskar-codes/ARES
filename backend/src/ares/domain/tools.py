from typing import Any, Literal, Dict
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class ToolSpec(BaseModel):
    name: str
    version: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    allowed_modes: list[str]
    allowed_roles: list[str]
    billing_class: Literal["local", "public_free", "gemini_paid"]
    network_target_policy: str
    timeout_seconds: float
    byte_limit: int
    result_limit: int
    idempotent: bool
    evidence_publication_policy: str

class ToolContext(BaseModel):
    workspace_id: UUID
    run_id: UUID
    node_id: UUID | None = None
    lease_token: UUID
    deadline: datetime
    policy_version: str
    remaining_budgets: Dict[str, float]
    permitted_asset_ids: list[UUID]
    permitted_source_ids: list[UUID]

ToolErrorCategory = Literal[
    "not_authorized",
    "invalid_input",
    "rate_limited",
    "unavailable",
    "deadline",
    "unsupported"
]

class ToolResult(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)
    source_ids: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    retrieval_timestamp: datetime | None = None
    capture_timestamp: datetime | None = None
    license: str | None = None
    attribution: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error_category: ToolErrorCategory | None = None
    error_message: str | None = None
