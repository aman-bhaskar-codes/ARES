from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select

from ares.adapters.db import (
    ArtifactRow,
    EvidenceRow,
    VisualizationDatasetRow,
    VisualizationRow,
)
from ares.domain.models import (
    ArtifactView,
    RunCreate,
)
from ares.domain.visualizations import (
    VisualizationDraft,
    VisualizationView,
    validate_visualization_dataset,
)


from ares.ports.repositories import NotFoundError
from ares.adapters.persistence.base import SqlRepositoryBase


def _hash_request(payload: RunCreate) -> str:
    encoded = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()




class SqlArtifactRepository(SqlRepositoryBase):
    def create_artifact(
        self,
        *,
        run_id: UUID,
        format: str,
        file_name: str,
        content_type: str,
        blob_key: str,
        byte_count: int,
        content_hash: str,
    ) -> ArtifactView:
        with self._sessions.begin() as session:
            if self._run_row(session, run_id) is None:
                raise NotFoundError("run not found")
            row = ArtifactRow(
                run_id=run_id,
                format=format,
                file_name=file_name,
                content_type=content_type,
                blob_key=blob_key,
                byte_count=byte_count,
                content_hash=content_hash,
            )
            session.add(row)
            session.flush()
            return ArtifactView(
                id=row.id,
                run_id=row.run_id,
                format=row.format,
                file_name=row.file_name,
                content_type=row.content_type,
                byte_count=row.byte_count,
                content_hash=row.content_hash,
                download_url=f"/api/v1/artifacts/{row.id}",
                created_at=row.created_at,
            )

    def save_visualization(self, run_id: UUID, draft: VisualizationDraft) -> VisualizationView:
        """Persist one backend-approved visualization idempotently.

        Persistence is a provenance boundary, not just a serializer: the bounded dataset
        schema is revalidated here, every embedded evidence/source ID must be represented
        by lineage, and every lineage reference must resolve to evidence from this exact
        run with matching source, segment and locator. This prevents future callers from
        smuggling cross-run or cross-workspace references into a visual artifact.
        """
        dataset_json, dataset_evidence_ids, dataset_source_ids = validate_visualization_dataset(
            draft.kind, draft.dataset
        )
        lineage_by_evidence = {item.evidence_id: item for item in draft.lineage}
        if len(lineage_by_evidence) != len(draft.lineage):
            raise ValueError("visualization lineage evidence ids must be unique")
        if not dataset_evidence_ids.issubset(lineage_by_evidence):
            raise ValueError("visualization dataset references evidence missing from lineage")
        lineage_source_ids = {item.source_id for item in draft.lineage}
        if not dataset_source_ids.issubset(lineage_source_ids):
            raise ValueError("visualization dataset references sources missing from lineage")

        lineage_json = [item.model_dump(mode="json") for item in draft.lineage]
        dataset_payload = json.dumps(
            {"dataset": dataset_json, "lineage": lineage_json},
            sort_keys=True,
            separators=(",", ":"),
        )
        content_hash = hashlib.sha256(dataset_payload.encode()).hexdigest()
        spec_json = draft.spec.model_dump(mode="json")
        spec_payload = json.dumps(
            {
                "kind": draft.kind.value,
                "title": draft.title,
                "description": draft.description,
                "spec": spec_json,
                "dataset_hash": content_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        spec_hash = hashlib.sha256(spec_payload.encode()).hexdigest()

        with self._sessions.begin() as session:
            run = self._run_row(session, run_id)
            if run is None:
                raise NotFoundError("run not found")

            if draft.lineage:
                evidence_rows = session.scalars(
                    select(EvidenceRow).where(
                        EvidenceRow.run_id == run_id,
                        EvidenceRow.id.in_(lineage_by_evidence),
                    )
                ).all()
                evidence_by_id = {row.id: row for row in evidence_rows}
                if set(evidence_by_id) != set(lineage_by_evidence):
                    raise ValueError(
                        "visualization lineage must resolve to evidence from the same run"
                    )
                for evidence_id, ref in lineage_by_evidence.items():
                    evidence = evidence_by_id[evidence_id]
                    if evidence.source_id != ref.source_id:
                        raise ValueError(
                            "visualization lineage source does not match persisted evidence"
                        )
                    if evidence.segment_id != ref.segment_id:
                        raise ValueError(
                            "visualization lineage segment does not match persisted evidence"
                        )
                    if evidence.locator != ref.locator:
                        raise ValueError(
                            "visualization lineage locator does not match persisted evidence"
                        )

            dataset = session.scalar(
                select(VisualizationDatasetRow).where(
                    VisualizationDatasetRow.run_id == run_id,
                    VisualizationDatasetRow.dataset_kind == draft.kind.value,
                    VisualizationDatasetRow.content_hash == content_hash,
                )
            )
            if dataset is None:
                dataset = VisualizationDatasetRow(
                    workspace_id=run.workspace_id,
                    run_id=run_id,
                    schema_version=1,
                    dataset_kind=draft.kind.value,
                    dataset_json=dataset_json,
                    lineage_json=lineage_json,
                    content_hash=content_hash,
                )
                session.add(dataset)
                session.flush()

            row = session.scalar(
                select(VisualizationRow).where(
                    VisualizationRow.run_id == run_id,
                    VisualizationRow.kind == draft.kind.value,
                    VisualizationRow.spec_hash == spec_hash,
                )
            )
            if row is None:
                row = VisualizationRow(
                    workspace_id=run.workspace_id,
                    run_id=run_id,
                    dataset_id=dataset.id,
                    schema_version=1,
                    kind=draft.kind.value,
                    title=draft.title,
                    description=draft.description,
                    approved_spec_json=spec_json,
                    spec_hash=spec_hash,
                    export_metadata_json=draft.export_metadata,
                )
                session.add(row)
                session.flush()
            return self._visualization_view(row, dataset)
