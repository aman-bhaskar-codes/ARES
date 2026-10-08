from pydantic import BaseModel, Field
from typing import Literal, Dict, Any
from uuid import UUID
from datetime import datetime

ReportSectionKind = Literal[
    "overview",
    "findings",
    "comparison",
    "methodology",
    "conflicts",
    "limitations",
    "next_steps"
]

ReportTemplate = Literal[
    "concise_answer",
    "research_brief",
    "literature_review",
    "technical_comparison"
]

class ReportSection(BaseModel):
    kind: ReportSectionKind
    title: str
    content: str
    claim_references: list[UUID] = Field(default_factory=list)

class ReportDocument(BaseModel):
    report_id: UUID
    run_id: UUID
    workspace_id: UUID
    schema_version: str = "1.0"
    template_version: ReportTemplate
    title: str
    research_question: str
    scope_date: datetime | None = None
    language: str = "en"
    sections: list[ReportSection] = Field(default_factory=list)
    assessed_claim_references: list[UUID] = Field(default_factory=list)
    evidence_references: list[UUID] = Field(default_factory=list)
    table_calculation_references: list[UUID] = Field(default_factory=list)
    visualization_references: list[UUID] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    bibliography: list[Dict[str, Any]] = Field(default_factory=list)
    generation_identity: str | None = None
    profile_identity: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    previous_revision_id: UUID | None = None
