from __future__ import annotations

import csv
from collections import defaultdict
from io import StringIO
import re
from uuid import UUID

from ares.application.repository import NotFoundError, Repository
from ares.domain.models import EvidenceView, RunStatus
from ares.domain.visualizations import (
    ChartPoint,
    ComparisonMatrixDataset,
    ComparisonMatrixRow,
    EvidenceGraphDataset,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    NumericChartDataset,
    TimelineDataset,
    TimelineEvent,
    VisualizationDraft,
    VisualizationKind,
    VisualizationLineageRef,
    VisualizationSpec,
    VisualizationView,
)


class VisualizationExportError(ValueError):
    pass


def _spreadsheet_safe(value: object) -> str:
    # Formula injection is a *string* hazard. Preserve real numeric cells, including
    # negatives, as numeric CSV text so integrity/analysis is not degraded by the
    # security guard itself. Booleans are intentionally treated as text.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _csv_bytes(rows: list[list[object]]) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in rows:
        writer.writerow([_spreadsheet_safe(value) for value in row])
    return buffer.getvalue().encode("utf-8")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug[:96] or "ares-visualization") + ".csv"


class VisualizationService:
    """Build small, deterministic, evidence-linked visual artifacts for completed runs.

    This service never evaluates model-provided JavaScript/options or parses numbers from answer
    prose. It only uses persisted M10 claim/evidence relations, publication dates, facet coverage,
    and normalized table cells that already resolve to run evidence.
    """

    def __init__(
        self, repository: Repository, *, max_graph_nodes: int = 100, max_graph_edges: int = 200
    ):
        self.repository = repository
        self.max_graph_nodes = min(max(1, max_graph_nodes), 100)
        self.max_graph_edges = min(max(1, max_graph_edges), 200)

    def list_for_run(self, run_id: UUID) -> list[VisualizationView]:
        """Return already-published visual artifacts without mutating run state.

        Generation belongs to the worker path so GET requests remain read-only and viewer
        sessions never need insert authority merely to inspect a completed run.
        """
        self.repository.get_run(run_id)
        return self.repository.list_visualizations(run_id)

    def export_csv(self, run_id: UUID, visualization_id: UUID) -> tuple[str, bytes]:
        """Export one already-approved visualization as deterministic lineage-bearing CSV."""
        view = next(
            (item for item in self.list_for_run(run_id) if item.id == visualization_id), None
        )
        if view is None:
            raise NotFoundError("visualization not found")
        if not view.approved_spec.allow_download_csv:
            raise VisualizationExportError("CSV export is disabled for this visualization kind")

        lineage_sources = {str(ref.evidence_id): str(ref.source_id) for ref in view.data_lineage}

        def evidence_sources(evidence_ids: list[UUID]) -> str:
            source_ids = (
                lineage_sources.get(str(evidence_id), "")
                for evidence_id in evidence_ids
                if lineage_sources.get(str(evidence_id))
            )
            return "|".join(dict.fromkeys(source_ids))

        rows: list[list[object]]
        if view.kind is VisualizationKind.COMPARISON_MATRIX:
            dataset = ComparisonMatrixDataset.model_validate(view.dataset)
            rows = [
                [
                    "facet",
                    "status",
                    "supporting_count",
                    "conflicting_count",
                    "independent_origin_count",
                    "supporting_evidence_ids",
                    "conflicting_evidence_ids",
                    "source_ids",
                    "rationale",
                ]
            ]
            for row in dataset.rows:
                evidence_ids = row.supporting_evidence_ids + row.conflicting_evidence_ids
                rows.append(
                    [
                        row.facet,
                        row.status,
                        row.supporting_count,
                        row.conflicting_count,
                        row.independent_origin_count,
                        "|".join(map(str, row.supporting_evidence_ids)),
                        "|".join(map(str, row.conflicting_evidence_ids)),
                        evidence_sources(evidence_ids),
                        row.rationale,
                    ]
                )
        elif view.kind in {
            VisualizationKind.BAR,
            VisualizationKind.LINE,
            VisualizationKind.SCATTER,
        }:
            dataset = NumericChartDataset.model_validate(view.dataset)
            rows = [
                [
                    "label",
                    "value",
                    "unit",
                    "series",
                    "transform",
                    "transform_note",
                    "evidence_ids",
                    "source_ids",
                ]
            ]
            for point in dataset.points:
                rows.append(
                    [
                        point.label,
                        point.value,
                        point.unit,
                        point.series,
                        point.transform,
                        point.transform_note,
                        "|".join(map(str, point.evidence_ids)),
                        evidence_sources(point.evidence_ids),
                    ]
                )
        elif view.kind is VisualizationKind.TIMELINE:
            dataset = TimelineDataset.model_validate(view.dataset)
            rows = [["event_at", "label", "source_id", "uncertainty", "evidence_ids"]]
            for event in dataset.events:
                rows.append(
                    [
                        event.event_at.isoformat(),
                        event.label,
                        event.source_id,
                        event.uncertainty,
                        "|".join(map(str, event.evidence_ids)),
                    ]
                )
        else:
            raise VisualizationExportError(
                "CSV export is not supported for this visualization kind"
            )
        return _slug(view.title), _csv_bytes(rows)

    def generate_for_run(self, run_id: UUID) -> list[VisualizationView]:
        """Generate deterministic visual artifacts for a terminal run, idempotently."""
        run = self.repository.get_run(run_id)
        if run.status not in {RunStatus.COMPLETED, RunStatus.PARTIAL}:
            return self.repository.list_visualizations(run_id)

        quality = self.repository.get_run_quality(run_id)
        evidence = self.repository.list_run_evidence(run_id)
        evidence_by_id = {item.id: item for item in evidence}

        drafts = [
            self._comparison_matrix(quality.facets, evidence_by_id),
            self._numeric_chart(run_id, evidence_by_id),
            self._timeline(evidence),
            self._evidence_map(quality.evidence_relations, evidence_by_id),
        ]
        for draft in drafts:
            if draft is not None:
                self.repository.save_visualization(run_id, draft)
        return self.repository.list_visualizations(run_id)

    @staticmethod
    def _lineage(
        evidence_ids: list[UUID], evidence_by_id: dict[UUID, EvidenceView]
    ) -> list[VisualizationLineageRef]:
        seen: set[UUID] = set()
        lineage: list[VisualizationLineageRef] = []
        for evidence_id in evidence_ids:
            if evidence_id in seen:
                continue
            item = evidence_by_id.get(evidence_id)
            if item is None:
                continue
            seen.add(evidence_id)
            lineage.append(
                VisualizationLineageRef(
                    evidence_id=item.id,
                    source_id=item.source.id,
                    segment_id=item.segment_id,
                    locator=item.locator,
                )
            )
        return lineage

    def _comparison_matrix(
        self, facets, evidence_by_id: dict[UUID, EvidenceView]
    ) -> VisualizationDraft | None:
        if not facets:
            return None
        rows = [
            ComparisonMatrixRow(
                facet=facet.facet_key,
                status=facet.status,
                supporting_count=len(facet.supporting_evidence_ids),
                conflicting_count=len(facet.conflicting_evidence_ids),
                independent_origin_count=facet.independent_origin_count,
                supporting_evidence_ids=facet.supporting_evidence_ids,
                conflicting_evidence_ids=facet.conflicting_evidence_ids,
                rationale=facet.rationale,
            )
            for facet in facets[:100]
        ]
        dataset = ComparisonMatrixDataset(rows=rows)
        ids = [
            evidence_id
            for row in rows
            for evidence_id in row.supporting_evidence_ids + row.conflicting_evidence_ids
        ]
        return VisualizationDraft(
            kind=VisualizationKind.COMPARISON_MATRIX,
            title="Evidence comparison",
            description="Facet-by-facet coverage using stored supporting and conflicting evidence relationships.",
            dataset=dataset.model_dump(mode="json"),
            spec=VisualizationSpec(kind=VisualizationKind.COMPARISON_MATRIX),
            lineage=self._lineage(ids, evidence_by_id),
            export_metadata={
                "csv_columns": [
                    "facet",
                    "status",
                    "supporting_count",
                    "conflicting_count",
                    "independent_origin_count",
                ]
            },
        )

    def _numeric_chart(
        self, run_id: UUID, evidence_by_id: dict[UUID, EvidenceView]
    ) -> VisualizationDraft | None:
        candidates = self.repository.list_run_numeric_table_points(run_id)
        groups: dict[tuple[UUID, int, str | None], list] = defaultdict(list)
        for candidate in candidates:
            groups[(candidate.table_id, candidate.column, candidate.unit)].append(candidate)
        eligible = [group for group in groups.values() if len(group) >= 2]
        if not eligible:
            return None
        points_source = sorted(
            eligible, key=lambda group: (-len(group), str(group[0].table_id), group[0].column)
        )[0][:200]
        points = [
            ChartPoint(
                id=f"{candidate.table_id}:{candidate.row}:{candidate.column}",
                label=candidate.label,
                value=candidate.value,
                unit=candidate.unit,
                evidence_ids=[candidate.evidence_id],
                transform="direct",
                transform_note="Direct normalized value from the cited structured table cell.",
            )
            for candidate in points_source
        ]
        dataset = NumericChartDataset(points=points)
        unit = next((point.unit for point in points if point.unit), None)
        table_key = points_source[0].table_key
        return VisualizationDraft(
            kind=VisualizationKind.BAR,
            title=f"Sourced values · {table_key}",
            description="Only directly cited numeric cells from one table column are plotted; mixed units are rejected.",
            dataset=dataset.model_dump(mode="json"),
            spec=VisualizationSpec(
                kind=VisualizationKind.BAR, x_field="label", y_field="value", unit=unit
            ),
            lineage=self._lineage(
                [candidate.evidence_id for candidate in points_source], evidence_by_id
            ),
            export_metadata={
                "csv_columns": ["label", "value", "unit", "evidence_ids"],
                "formula_escape": True,
            },
        )

    def _timeline(self, evidence: list[EvidenceView]) -> VisualizationDraft | None:
        grouped: dict[UUID, list[EvidenceView]] = defaultdict(list)
        for item in evidence:
            if item.source.published_at is not None:
                grouped[item.source.id].append(item)
        if not grouped:
            return None
        events = [
            TimelineEvent(
                id=str(source_id),
                label=items[0].source.title,
                event_at=items[0].source.published_at,
                source_id=source_id,
                evidence_ids=[item.id for item in items[:100]],
                uncertainty="Publication date from source metadata; retrieval time is intentionally not substituted.",
            )
            for source_id, items in grouped.items()
        ]
        events.sort(key=lambda item: (item.event_at, item.label))
        dataset = TimelineDataset(events=events[:200])
        evidence_by_id = {item.id: item for item in evidence}
        return VisualizationDraft(
            kind=VisualizationKind.TIMELINE,
            title="Source publication timeline",
            description="Publication dates for sources that contributed run evidence. Unknown publication dates are omitted rather than replaced by fetch time.",
            dataset=dataset.model_dump(mode="json"),
            spec=VisualizationSpec(kind=VisualizationKind.TIMELINE),
            lineage=self._lineage(
                [evidence_id for event in dataset.events for evidence_id in event.evidence_ids],
                evidence_by_id,
            ),
            export_metadata={"csv_columns": ["event_at", "label", "source_id", "evidence_ids"]},
        )

    def _evidence_map(
        self, relations, evidence_by_id: dict[UUID, EvidenceView]
    ) -> VisualizationDraft | None:
        if not relations:
            return None
        nodes: dict[str, EvidenceGraphNode] = {}
        edges: list[EvidenceGraphEdge] = []

        def add_node(node: EvidenceGraphNode) -> bool:
            if node.id in nodes:
                return True
            if len(nodes) >= self.max_graph_nodes:
                return False
            nodes[node.id] = node
            return True

        for relation in relations:
            if len(edges) >= self.max_graph_edges:
                break
            evidence = evidence_by_id.get(relation.evidence_id)
            if evidence is None:
                continue
            claim_id = f"claim:{relation.claim_id}"
            evidence_id = f"evidence:{relation.evidence_id}"
            source_id = f"source:{evidence.source.id}"
            required = [
                EvidenceGraphNode(id=claim_id, kind="claim", label=relation.claim_text[:500]),
                EvidenceGraphNode(
                    id=evidence_id,
                    kind="evidence",
                    label=(evidence.text.strip() or evidence.locator)[:500],
                    evidence_id=evidence.id,
                    source_id=evidence.source.id,
                    support_status=evidence.support_status,
                ),
                EvidenceGraphNode(
                    id=source_id,
                    kind="source",
                    label=evidence.source.title[:500],
                    source_id=evidence.source.id,
                ),
            ]
            # Reserve a relation's complete node set before mutating the graph. Otherwise a
            # cap hit partway through claim/evidence/source insertion can publish orphan nodes.
            missing_ids = {node.id for node in required if node.id not in nodes}
            if len(nodes) + len(missing_ids) > self.max_graph_nodes:
                break
            for node in required:
                add_node(node)
            edge_id = f"{claim_id}:{relation.relation}:{evidence_id}"
            edges.append(
                EvidenceGraphEdge(
                    id=edge_id,
                    source=claim_id,
                    target=evidence_id,
                    relation=relation.relation,
                    evidence_id=evidence.id,
                    rationale=relation.rationale,
                )
            )
            origin_edge_id = f"{evidence_id}:origin:{source_id}"
            if len(edges) < self.max_graph_edges and not any(
                edge.id == origin_edge_id for edge in edges
            ):
                edges.append(
                    EvidenceGraphEdge(
                        id=origin_edge_id,
                        source=evidence_id,
                        target=source_id,
                        relation="originates_from",
                        evidence_id=evidence.id,
                    )
                )

        dataset = EvidenceGraphDataset(nodes=list(nodes.values()), edges=edges)
        if not dataset.nodes or not dataset.edges:
            return None
        return VisualizationDraft(
            kind=VisualizationKind.EVIDENCE_MAP,
            title="Evidence relationship map",
            description="A bounded neighborhood of accepted claims, their evidence, and source origins. Edges preserve support/contradiction/context semantics and do not imply causation.",
            dataset=dataset.model_dump(mode="json"),
            spec=VisualizationSpec(kind=VisualizationKind.EVIDENCE_MAP, allow_download_csv=False),
            lineage=self._lineage(
                [node.evidence_id for node in dataset.nodes if node.evidence_id is not None],
                evidence_by_id,
            ),
            export_metadata={"node_cap": self.max_graph_nodes, "edge_cap": self.max_graph_edges},
        )
