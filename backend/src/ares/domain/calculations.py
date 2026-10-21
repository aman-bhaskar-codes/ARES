from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

OperationType = Literal["filter", "group", "aggregate", "join"]

class CalculationLineage(BaseModel):
    calculation_id: UUID
    operation: OperationType
    version: str = "1.0"
    params: dict[str, Any]
    input_hashes: list[str] = Field(default_factory=list)
    dataset_ids: list[UUID] = Field(default_factory=list)
    cell_evidence_ids: list[UUID] = Field(default_factory=list)
    result_hash: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class DerivedValue(BaseModel):
    value: float | str | int
    unit: str | None = None
    lineage_id: UUID
    is_computed: bool = True
