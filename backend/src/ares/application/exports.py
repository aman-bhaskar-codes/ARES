from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID

from ares.application.repository import Repository
from ares.domain.models import ArtifactView, ExportCreate, RunStatus
from ares.ports.storage import BlobStore
import html

logger = logging.getLogger(__name__)

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
        elif request.format == "html":
            payload = self._html(run, evidence).encode("utf-8")
            extension = "html"
            content_type = "text/html; charset=utf-8"
        elif request.format == "pdf":
            payload = self._pdf(run, evidence)
            extension = "pdf"
            content_type = "application/pdf"
        else:
            payload = json.dumps(
                self._manifest(run, evidence), ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
            extension = "json"
            content_type = "application/json"
            
        digest = hashlib.sha256(payload).hexdigest()
        blob_key = self.blobs.put_bytes("artifacts", payload)
        file_name = f"ares-run-{run.id}.{extension}"
        
        # Idempotent artifact job based on hash
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
            "export_provenance": {
                "system": "ARES V3",
                "contains_private_blobs": False
            }
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
                identifier = (
                    f" · {item.source.canonical_identifier}"
                    if item.source.canonical_identifier
                    else ""
                )
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

    def _html(self, run, evidence) -> str:
        md = self._markdown(run, evidence)
        escaped_md = html.escape(md)
        return f"<!DOCTYPE html><html><head><title>Export {run.id}</title></head><body><pre>{escaped_md}</pre></body></html>"
        
    def _pdf(self, run, evidence) -> bytes:
        html_str = self._html(run, evidence)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ExportError("PDF renderer is unavailable. Export Markdown or HTML instead.") from exc
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(timeout=15_000)
                try:
                    context = browser.new_context(offline=True, java_script_enabled=False)
                    page = context.new_page()
                    page.set_content(html_str, timeout=15_000)
                    return page.pdf()
                finally:
                    browser.close()
        except Exception as exc:
            logger.exception("PDF rendering failed")
            raise ExportError("PDF renderer failed. Export Markdown or HTML instead.") from exc
