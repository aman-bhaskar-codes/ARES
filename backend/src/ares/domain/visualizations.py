from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class VisualizationKind(StrEnum):
    COMPARISON_MATRIX = "comparison_matrix"
    BAR = "bar"
    LINE = "line"
    SCATTER = "scatter"
    TIMELINE = "timeline"
    EVIDENCE_MAP = "evidence_map"


class VisualizationLineageRef(BaseModel):
    evidence_id: UUID
    source_id: UUID
    segment_id: UUID | None = None
    locator: str = ""


class ComparisonMatrixRow(BaseModel):
    facet: str = Field(min_length=1, max_length=160)
    status: Literal["supported", "conflicting", "missing"]
    supporting_count: int = Field(default=0, ge=0)
    conflicting_count: int = Field(default=0, ge=0)
    independent_origin_count: int = Field(default=0, ge=0)
    supporting_evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    conflicting_evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    rationale: str = Field(default="", max_length=2_000)


class ComparisonMatrixDataset(BaseModel):
    rows: list[ComparisonMatrixRow] = Field(default_factory=list, max_length=100)


class ChartPoint(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=240)
    value: float = Field(allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=80)
    series: str | None = Field(default=None, max_length=160)
    evidence_ids: list[UUID] = Field(min_length=1, max_length=32)
    transform: Literal["direct", "aggregate", "difference", "ratio", "unit_conversion"] = "direct"
    transform_note: str = Field(default="", max_length=1_000)


class NumericChartDataset(BaseModel):
    points: list[ChartPoint] = Field(min_length=2, max_length=200)

    @model_validator(mode="after")
    def validate_units(self) -> "NumericChartDataset":
        nonempty = {point.unit for point in self.points if point.unit}
        if len(nonempty) > 1:
            raise ValueError("numeric chart points must use one comparable unit")
        return self


class TimelineEvent(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=300)
    event_at: datetime
    source_id: UUID
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    uncertainty: str = Field(default="", max_length=1_000)


class TimelineDataset(BaseModel):
    events: list[TimelineEvent] = Field(min_length=1, max_length=200)


class EvidenceGraphNode(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    kind: Literal["claim", "evidence", "source"]
    label: str = Field(min_length=1, max_length=500)
    evidence_id: UUID | None = None
    source_id: UUID | None = None
    support_status: str | None = Field(default=None, max_length=40)


class EvidenceGraphEdge(BaseModel):
    id: str = Field(min_length=1, max_length=220)
    source: str = Field(min_length=1, max_length=160)
    target: str = Field(min_length=1, max_length=160)
    relation: Literal["supports", "contradicts", "contextualizes", "originates_from"]
    evidence_id: UUID | None = None
    rationale: str = Field(default="", max_length=1_000)


class EvidenceGraphDataset(BaseModel):
    nodes: list[EvidenceGraphNode] = Field(default_factory=list, max_length=100)
    edges: list[EvidenceGraphEdge] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_graph(self) -> "EvidenceGraphDataset":
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("evidence graph node ids must be unique")
        for edge in self.edges:
            if edge.source not in ids or edge.target not in ids:
                raise ValueError("evidence graph edge references an unknown node")
        return self


def validate_visualization_dataset(
    kind: VisualizationKind, dataset: dict[str, object]
) -> tuple[dict[str, object], set[UUID], set[UUID]]:
    """Validate a persisted visualization dataset and return its provenance references.

    Visual artifacts are intentionally not an open-ended model schema. Every supported
    kind is parsed through a bounded ARES model before persistence, and every embedded
    evidence/source reference is surfaced so the repository can enforce same-run lineage.
    """
    if kind is VisualizationKind.COMPARISON_MATRIX:
        parsed = ComparisonMatrixDataset.model_validate(dataset)
        evidence_ids = {
            evidence_id
            for row in parsed.rows
            for evidence_id in row.supporting_evidence_ids + row.conflicting_evidence_ids
        }
        source_ids: set[UUID] = set()
    elif kind in {VisualizationKind.BAR, VisualizationKind.LINE, VisualizationKind.SCATTER}:
        parsed = NumericChartDataset.model_validate(dataset)
        evidence_ids = {evidence_id for point in parsed.points for evidence_id in point.evidence_ids}
        source_ids = set()
    elif kind is VisualizationKind.TIMELINE:
        parsed = TimelineDataset.model_validate(dataset)
        evidence_ids = {evidence_id for event in parsed.events for evidence_id in event.evidence_ids}
        source_ids = {event.source_id for event in parsed.events}
    elif kind is VisualizationKind.EVIDENCE_MAP:
        parsed = EvidenceGraphDataset.model_validate(dataset)
        evidence_ids = {
            value
            for value in (
                [node.evidence_id for node in parsed.nodes]
                + [edge.evidence_id for edge in parsed.edges]
            )
            if value is not None
        }
        source_ids = {node.source_id for node in parsed.nodes if node.source_id is not None}
    else:  # pragma: no cover - StrEnum exhaustiveness guard
        raise ValueError(f"unsupported visualization kind: {kind}")
    return parsed.model_dump(mode="json"), evidence_ids, source_ids


class VisualizationSpec(BaseModel):
    kind: VisualizationKind
    x_field: str | None = Field(default=None, max_length=80)
    y_field: str | None = Field(default=None, max_length=80)
    series_field: str | None = Field(default=None, max_length=80)
    unit: str | None = Field(default=None, max_length=80)
    renderer: Literal["svg", "canvas"] = "svg"
    max_points: int = Field(default=200, ge=1, le=200)
    allow_download_csv: bool = True
    accessible_table: bool = True

    @model_validator(mode="after")
    def validate_mapping(self) -> "VisualizationSpec":
        if self.kind in {VisualizationKind.BAR, VisualizationKind.LINE, VisualizationKind.SCATTER}:
            if self.x_field != "label" or self.y_field != "value":
                raise ValueError("numeric chart fields are restricted to label/value")
        if not self.accessible_table:
            raise ValueError("visualizations must retain an accessible table alternative")
        return self


class NumericTablePointCandidate(BaseModel):
    evidence_id: UUID
    source_id: UUID
    segment_id: UUID
    table_id: UUID
    table_key: str
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=240)
    value: float = Field(allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=80)


class VisualizationDraft(BaseModel):
    kind: VisualizationKind
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2_000)
    dataset: dict[str, object]
    spec: VisualizationSpec
    lineage: list[VisualizationLineageRef] = Field(default_factory=list, max_length=500)
    export_metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> "VisualizationDraft":
        if self.spec.kind != self.kind:
            raise ValueError("visualization kind must match approved spec kind")

        normalized, _, _ = validate_visualization_dataset(self.kind, self.dataset)
        item_count = 0
        if self.kind is VisualizationKind.COMPARISON_MATRIX:
            item_count = len(normalized.get("rows", []))
        elif self.kind in {VisualizationKind.BAR, VisualizationKind.LINE, VisualizationKind.SCATTER}:
            item_count = len(normalized.get("points", []))
        elif self.kind is VisualizationKind.TIMELINE:
            item_count = len(normalized.get("events", []))
        if item_count > self.spec.max_points:
            raise ValueError("visualization dataset exceeds approved spec max_points")
        return self


class VisualizationView(BaseModel):
    id: UUID
    run_id: UUID
    dataset_id: UUID
    kind: VisualizationKind
    title: str
    description: str = ""
    schema_version: int = 1
    dataset: dict[str, object]
    approved_spec: VisualizationSpec
    data_lineage: list[VisualizationLineageRef] = Field(default_factory=list)
    export_metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
