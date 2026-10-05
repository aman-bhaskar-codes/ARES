from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from ares.adapters.db import (
    DocumentTableCellRow,
    DocumentTableRow,
    EvidenceRow,
    EvidenceSegmentRow,
    ExtractionVersionRow,
    AssetVersionRow,
    VisualizationDatasetRow,
    VisualizationRow,
)
from ares.application.repository import Repository
from ares.application.visualizations import VisualizationService
from ares.domain.decisions import FacetAssessment, FacetStatus
from ares.domain.models import (
    AssessmentState,
    FetchedDocument,
    FinalizedClaim,
    RunCreate,
    RunMode,
    RunStatus,
    SupportStatus,
)
from ares.domain.research import EvidenceCandidate
from ares.domain.visualizations import (
    ChartPoint,
    EvidenceGraphDataset,
    NumericChartDataset,
    TimelineDataset,
    TimelineEvent,
    VisualizationDraft,
    VisualizationKind,
    VisualizationLineageRef,
    VisualizationSpec,
)


def _complete_run_with_evidence(repository: Repository, *, suffix: str = "base"):
    conversation = repository.create_conversation("M11 visual workspace")
    run, _ = repository.create_run(
        RunCreate(conversation_id=conversation.id, query="compare the evidence", mode=RunMode.QUICK),
        idempotency_key=f"m11-visual-{suffix}",
    )
    lease = repository.claim_next_job()
    assert lease is not None
    repository.set_status(run.id, RunStatus.PLANNING, lease_token=lease.token)
    repository.set_status(run.id, RunStatus.DISCOVERING, lease_token=lease.token)
    repository.set_status(run.id, RunStatus.CHECKING, lease_token=lease.token)

    published = datetime(2026, 1, 2, tzinfo=UTC)
    docs = [
        FetchedDocument(
            source_id=uuid4(), title="Study A", url="https://example.com/a", final_url="https://example.com/a",
            text="Study A reports 20 units for the measured outcome and describes the experimental setting.",
            content_hash="a" * 64, extraction_method="fixture", published_at=published,
        ),
        FetchedDocument(
            source_id=uuid4(), title="Study B", url="https://example.com/b", final_url="https://example.com/b",
            text="Study B reports a conflicting result for the same outcome under a different setting.",
            content_hash="b" * 64, extraction_method="fixture", published_at=datetime(2026, 2, 3, tzinfo=UTC),
        ),
    ]
    packets = []
    for doc in docs:
        candidate = EvidenceCandidate(
            source_id=doc.source_id, title=doc.title, url=doc.url, text=doc.text,
            locator="fixture", char_start=0, char_end=len(doc.text),
        )
        packets.extend(repository.persist_document_evidence(
            run.id, document=doc, candidates=[candidate], provider="fixture", lease_token=lease.token,
        ))
    first, second = packets
    repository.persist_facet_coverage(
        run.id,
        [FacetAssessment(
            facet="measured outcome",
            status=FacetStatus.CONFLICTING,
            supporting_evidence_ids=[first.evidence_id],
            conflicting_evidence_ids=[second.evidence_id],
            rationale="The two sources report different scoped outcomes.",
        )],
        checker_method="fixture",
        checker_version="m11-test",
        lease_token=lease.token,
    )
    repository.set_status(run.id, RunStatus.SYNTHESIZING, lease_token=lease.token)
    repository.finalize_answer(
        run.id,
        "### Comparison\nThe sources disagree under different settings.",
        [FinalizedClaim(
            text="The sources disagree under different settings.",
            evidence_ids=[first.evidence_id, second.evidence_id],
            support_status=SupportStatus.CONFLICTING,
            checker_method="fixture",
            checker_version="m11-test",
            assessment_state=AssessmentState.SEMANTIC_ASSESSED,
            assessment_rationale="Conflicting scoped results.",
            evidence_relations={str(first.evidence_id): "supports", str(second.evidence_id): "contradicts"},
            evidence_rationales={str(first.evidence_id): "reported result", str(second.evidence_id): "opposing result"},
        )],
        [],
        lease_token=lease.token,
    )
    repository.set_status(run.id, RunStatus.COMPLETED, lease_token=lease.token)
    repository.finish_job(lease)
    return run.id, first.evidence_id, second.evidence_id


def test_visualization_service_persists_idempotent_lineage_backed_views(repository: Repository) -> None:
    run_id, first_id, second_id = _complete_run_with_evidence(repository)
    service = VisualizationService(repository)

    assert service.list_for_run(run_id) == []
    first = service.generate_for_run(run_id)
    kinds = {item.kind for item in first}
    assert VisualizationKind.COMPARISON_MATRIX in kinds
    assert VisualizationKind.TIMELINE in kinds
    assert VisualizationKind.EVIDENCE_MAP in kinds
    assert VisualizationKind.BAR not in kinds  # no structured numeric table cells were cited

    second = service.generate_for_run(run_id)
    assert [item.id for item in second] == [item.id for item in first]
    lineage_ids = {ref.evidence_id for item in first for ref in item.data_lineage}
    assert {first_id, second_id}.issubset(lineage_ids)

    with repository._sessions() as session:
        assert len(session.scalars(select(VisualizationDatasetRow)).all()) == len(first)
        assert len(session.scalars(select(VisualizationRow)).all()) == len(first)


def test_numeric_chart_uses_only_cited_normalized_table_cells_with_same_unit(repository: Repository) -> None:
    run_id, first_id, _ = _complete_run_with_evidence(repository)
    with repository._sessions.begin() as session:
        evidence = session.get(EvidenceRow, first_id)
        assert evidence is not None
        run = repository._run_row(session, run_id)
        assert run is not None
        asset = AssetVersionRow(
            workspace_id=run.workspace_id,
            created_by_user_id=run.created_by_user_id,
            original_name="values.csv", original_blob_key="fixture/values.csv", sha256="c" * 64,
            mime_type="text/csv", byte_count=40, status="ready",
        )
        session.add(asset); session.flush()
        extraction = ExtractionVersionRow(
            workspace_id=run.workspace_id, asset_version_id=asset.id, parser_id="csv_builtin",
            parser_revision="m11-test", config_hash="d" * 64, status="ready", output_hash="e" * 64,
            completed_at=datetime.now(UTC),
        )
        session.add(extraction); session.flush()
        table = DocumentTableRow(
            workspace_id=run.workspace_id, extraction_version_id=extraction.id, table_key="table-1",
            rows=3, columns=2,
        )
        session.add(table); session.flush()
        header_name = DocumentTableCellRow(
            workspace_id=run.workspace_id, table_id=table.id, row_index=0, column_index=0,
            raw_text="Method", normalized_value_json="Method", is_header=True,
        )
        header_value = DocumentTableCellRow(
            workspace_id=run.workspace_id, table_id=table.id, row_index=0, column_index=1,
            raw_text="Score", normalized_value_json="Score", unit="ms", is_header=True,
        )
        session.add_all([header_name, header_value]); session.flush()

        for row_index, (label, value) in enumerate((("A", 20), ("B", 30)), start=1):
            label_cell = DocumentTableCellRow(
                workspace_id=run.workspace_id, table_id=table.id, row_index=row_index, column_index=0,
                raw_text=label, normalized_value_json=label,
            )
            segment = EvidenceSegmentRow(
                workspace_id=run.workspace_id, extraction_version_id=extraction.id, modality="table_cell",
                text=str(value), locator_json={"kind": "table_cells", "table_id": "table-1", "rows": [row_index], "columns": [1], "page": None},
                derivation_kind="csv_native", content_hash=(str(value) * 64)[:64],
            )
            session.add_all([label_cell, segment]); session.flush()
            value_cell = DocumentTableCellRow(
                workspace_id=run.workspace_id, table_id=table.id, segment_id=segment.id,
                row_index=row_index, column_index=1, raw_text=str(value), normalized_value_json=value, unit="ms",
            )
            session.add(value_cell)
            # Promote the exact structured cell into run evidence. Reuse the already-authorized source.
            cited = EvidenceRow(
                run_id=run_id, source_id=evidence.source_id, segment_id=segment.id,
                text=str(value), locator=f"table-1 row {row_index} column 1", support_status="supported",
                captured_at=datetime.now(UTC),
            )
            session.add(cited)

    views = VisualizationService(repository).generate_for_run(run_id)
    chart = next(item for item in views if item.kind is VisualizationKind.BAR)
    dataset = NumericChartDataset.model_validate(chart.dataset)
    assert [point.value for point in dataset.points] == [20.0, 30.0]
    assert all(point.unit == "ms" for point in dataset.points)
    assert all(point.evidence_ids for point in dataset.points)


def test_numeric_chart_schema_rejects_mixed_units() -> None:
    from ares.domain.visualizations import ChartPoint
    with pytest.raises(ValueError, match="one comparable unit"):
        NumericChartDataset(points=[
            ChartPoint(id="a", label="A", value=1, unit="ms", evidence_ids=[uuid4()]),
            ChartPoint(id="b", label="B", value=2, unit="kg", evidence_ids=[uuid4()]),
        ])


def test_numeric_chart_schema_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError):
        ChartPoint(id="nan", label="Invalid", value=float("nan"), unit="ms", evidence_ids=[uuid4()])
    with pytest.raises(ValueError):
        ChartPoint(id="inf", label="Invalid", value=float("inf"), unit="ms", evidence_ids=[uuid4()])


def test_visualization_draft_enforces_approved_max_points() -> None:
    evidence_ids = [uuid4(), uuid4()]
    dataset = NumericChartDataset(points=[
        ChartPoint(id="a", label="A", value=1, unit="ms", evidence_ids=[evidence_ids[0]]),
        ChartPoint(id="b", label="B", value=2, unit="ms", evidence_ids=[evidence_ids[1]]),
    ])
    with pytest.raises(ValueError, match="max_points"):
        VisualizationDraft(
            kind=VisualizationKind.BAR,
            title="Over-cap chart",
            dataset=dataset.model_dump(mode="json"),
            spec=VisualizationSpec(
                kind=VisualizationKind.BAR, x_field="label", y_field="value", unit="ms", max_points=1,
            ),
            lineage=[],
        )


def test_visualization_api_returns_validated_artifacts(tmp_path) -> None:
    from fastapi.testclient import TestClient
    from ares.adapters.db import Base, build_session_factory
    from ares.api.app import create_app
    from ares.api.settings import Settings

    db = f"sqlite+pysqlite:///{tmp_path / 'm11-api.sqlite3'}"
    engine, sessions = build_session_factory(db)
    Base.metadata.create_all(engine)
    repository = Repository(sessions)
    run_id, _, _ = _complete_run_with_evidence(repository)

    client = TestClient(create_app(Settings(ares_mode="demo", database_url=db, visualizations_enabled=True)))
    # GET is intentionally read-only: the worker publishes visual artifacts first.
    assert client.get(f"/api/v2/runs/{run_id}/visualizations").json() == []
    VisualizationService(repository).generate_for_run(run_id)
    response = client.get(f"/api/v2/runs/{run_id}/visualizations")
    assert response.status_code == 200
    payload = response.json()
    assert {item["kind"] for item in payload} >= {"comparison_matrix", "timeline", "evidence_map"}
    assert all(item["approved_spec"]["accessible_table"] is True for item in payload)



def test_visualization_csv_export_is_lineage_bearing_and_formula_safe(repository: Repository) -> None:
    run_id, first_id, second_id = _complete_run_with_evidence(repository, suffix="csv-export")
    evidence = {item.id: item for item in repository.list_run_evidence(run_id)}
    points = NumericChartDataset(points=[
        ChartPoint(id="a", label="=SUM(A1:A2)", value=-20, unit="ms", evidence_ids=[first_id]),
        ChartPoint(id="b", label="-HYPERLINK(\"https://invalid.example\")", value=30, unit="ms", evidence_ids=[second_id]),
    ])
    lineage = [
        VisualizationLineageRef(
            evidence_id=item.id, source_id=item.source.id, segment_id=item.segment_id, locator=item.locator,
        )
        for item in (evidence[first_id], evidence[second_id])
    ]
    view = repository.save_visualization(run_id, VisualizationDraft(
        kind=VisualizationKind.BAR,
        title="Formula-safe sourced values",
        dataset=points.model_dump(mode="json"),
        spec=VisualizationSpec(kind=VisualizationKind.BAR, x_field="label", y_field="value", unit="ms"),
        lineage=lineage,
    ))

    filename, content = VisualizationService(repository).export_csv(run_id, view.id)
    text = content.decode("utf-8")
    assert filename == "formula-safe-sourced-values.csv"
    assert "evidence_ids,source_ids" in text
    assert "'=SUM(A1:A2)" in text
    assert "'-HYPERLINK" in text
    assert ",-20.0,ms," in text  # legitimate negative numeric values remain numeric
    assert "'-20.0" not in text
    assert str(evidence[first_id].source.id) in text
    assert str(evidence[second_id].source.id) in text


def test_visualization_csv_api_is_download_only_and_rejects_graph_export(tmp_path) -> None:
    from fastapi.testclient import TestClient
    from ares.adapters.db import Base, build_session_factory
    from ares.api.app import create_app
    from ares.api.settings import Settings

    db = f"sqlite+pysqlite:///{tmp_path / 'm11-csv-api.sqlite3'}"
    engine, sessions = build_session_factory(db)
    Base.metadata.create_all(engine)
    repository = Repository(sessions)
    run_id, _, _ = _complete_run_with_evidence(repository, suffix="csv-api")
    views = VisualizationService(repository).generate_for_run(run_id)
    comparison = next(item for item in views if item.kind is VisualizationKind.COMPARISON_MATRIX)
    graph = next(item for item in views if item.kind is VisualizationKind.EVIDENCE_MAP)

    client = TestClient(create_app(Settings(ares_mode="demo", database_url=db, visualizations_enabled=True)))
    response = client.get(f"/api/v2/runs/{run_id}/visualizations/{comparison.id}/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=\"evidence-comparison.csv\"" == response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    assert "source_ids" in response.text
    export_spec = client.get("/openapi.json").json()["paths"][f"/api/v2/runs/{{run_id}}/visualizations/{{visualization_id}}/export.csv"]["get"]
    assert "text/csv" in export_spec["responses"]["200"]["content"]

    denied = client.get(f"/api/v2/runs/{run_id}/visualizations/{graph.id}/export.csv")
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "VISUALIZATION_EXPORT_UNAVAILABLE"

def test_evidence_map_reserves_complete_relation_nodes_before_graph_cap(repository: Repository) -> None:
    run_id, _, _ = _complete_run_with_evidence(repository, suffix="graph-cap")
    views = VisualizationService(repository, max_graph_nodes=4, max_graph_edges=200).generate_for_run(run_id)
    graph = EvidenceGraphDataset.model_validate(
        next(item for item in views if item.kind is VisualizationKind.EVIDENCE_MAP).dataset
    )
    referenced = {edge.source for edge in graph.edges} | {edge.target for edge in graph.edges}
    assert {node.id for node in graph.nodes} == referenced
    assert len(graph.nodes) == 3


def test_visualization_persistence_rejects_dataset_evidence_missing_from_lineage(repository: Repository) -> None:
    run_id, _, _ = _complete_run_with_evidence(repository, suffix="missing-lineage")
    view = next(
        item for item in VisualizationService(repository).generate_for_run(run_id)
        if item.kind is VisualizationKind.COMPARISON_MATRIX
    )
    draft = VisualizationDraft(
        kind=view.kind,
        title="Tampered comparison",
        dataset=view.dataset,
        spec=view.approved_spec,
        lineage=[],
    )
    with pytest.raises(ValueError, match="evidence missing from lineage"):
        repository.save_visualization(run_id, draft)


def test_visualization_persistence_rejects_cross_run_lineage(repository: Repository) -> None:
    first_run_id, _, _ = _complete_run_with_evidence(repository, suffix="target-run")
    second_run_id, second_evidence_id, _ = _complete_run_with_evidence(repository, suffix="foreign-run")
    foreign_evidence = next(item for item in repository.list_run_evidence(second_run_id) if item.id == second_evidence_id)
    event_at = foreign_evidence.source.published_at
    assert event_at is not None
    dataset = TimelineDataset(events=[TimelineEvent(
        id="foreign-source",
        label=foreign_evidence.source.title,
        event_at=event_at,
        source_id=foreign_evidence.source.id,
        evidence_ids=[foreign_evidence.id],
    )])
    draft = VisualizationDraft(
        kind=VisualizationKind.TIMELINE,
        title="Cross-run attempt",
        dataset=dataset.model_dump(mode="json"),
        spec=VisualizationSpec(kind=VisualizationKind.TIMELINE),
        lineage=[VisualizationLineageRef(
            evidence_id=foreign_evidence.id,
            source_id=foreign_evidence.source.id,
            segment_id=foreign_evidence.segment_id,
            locator=foreign_evidence.locator,
        )],
    )
    with pytest.raises(ValueError, match="same run"):
        repository.save_visualization(first_run_id, draft)
