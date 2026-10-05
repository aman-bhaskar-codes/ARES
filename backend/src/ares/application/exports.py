from __future__ import annotations

import hashlib
import json
from uuid import UUID

from ares.application.repository import Repository
from ares.domain.models import ArtifactView, ExportCreate, RunStatus
from ares.ports.storage import BlobStore


class ExportError(RuntimeError):
    pass


class ExportService:
    def __init__(self, repository: Repository, blobs: BlobStore):
        self.repository = repository
        self.blobs = blobs

    def create(self, run_id: UUID, request: ExportCreate) -> ArtifactView:
        run = self.repository.get_run(run_id)
        if run.status not in {RunStatus.COMPLETED, RunStatus.PARTIAL}:
            raise ExportError("only completed or partial runs can be exported")
        evidence = self.repository.list_run_evidence(run_id)
        if request.format == "markdown":
            payload = self._markdown(run, evidence).encode("utf-8")
            extension = "md"
            content_type = "text/markdown; charset=utf-8"
        else:
            payload = json.dumps(
                self._manifest(run, evidence), ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
            extension = "json"
            content_type = "application/json"
        digest = hashlib.sha256(payload).hexdigest()
        blob_key = self.blobs.put_bytes("artifacts", payload)
        file_name = f"ares-run-{run.id}.{extension}"
        return self.repository.create_artifact(
            run_id=run.id,
            format=request.format,
            file_name=file_name,
            content_type=content_type,
            blob_key=blob_key,
            byte_count=len(payload),
            content_hash=digest,
        )

    @staticmethod
    def _manifest(run, evidence) -> dict[str, object]:
        return {
            "schema_version": 1,
            "run": run.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }

    @staticmethod
    def _markdown(run, evidence) -> str:
        lines = [
            "# ARES research export",
            "",
            f"**Query:** {run.query}",
            f"**Mode:** {run.mode.value}",
            f"**Status:** {run.status.value}",
            f"**Run ID:** `{run.id}`",
            "",
        ]
        for block in run.answer_blocks:
            lines.append(block.markdown.strip())
            lines.append("")
            if block.claims:
                lines.append("## Claims")
                lines.append("")
                for claim in block.claims:
                    markers = " ".join(f"[{label}]" for label in claim.citation_labels)
                    lines.append(f"- {claim.text} {markers} — *{claim.support_status.value}*")
                lines.append("")
        if run.gaps:
            lines.extend(["## Remaining gaps", ""])
            lines.extend(f"- {gap}" for gap in run.gaps)
            lines.append("")
        if evidence:
            lines.extend(["## Evidence", ""])
            for index, item in enumerate(evidence, start=1):
                identifier = f" · {item.source.canonical_identifier}" if item.source.canonical_identifier else ""
                lines.append(
                    f"{index}. **{item.source.title}** ({item.source.domain}{identifier}) — "
                    f"{item.locator}. Retrieved {item.source.fetched_at.isoformat()}."
                )
                lines.append(f"   > {item.text.replace(chr(10), ' ')}")
                lines.append(f"   Source: {item.source.url}")
                lines.append(f"   Content hash: `{item.content_hash}`")
                lines.append("")
        lines.append("---")
        lines.append("Generated deterministically from persisted ARES run/evidence records.")
        return "\n".join(lines)
