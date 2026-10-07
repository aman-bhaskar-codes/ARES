from uuid import UUID, uuid4
from datetime import datetime, timezone
from ares.domain.reports import ReportDocument, ReportSection, ReportTemplate
from ares.domain.research import RunAssessment
from ares.application.repository import Repository

class ReportBuilder:
    def __init__(self, repository: Repository):
        self.repository = repository

    def build_report_from_assessment(
        self,
        workspace_id: UUID,
        run_id: UUID,
        template: ReportTemplate,
        assessment: RunAssessment,
        title: str,
        research_question: str
    ) -> ReportDocument:
        sections = []
        
        # Build sections from outline if present
        if assessment.outline:
            for outline_sec in assessment.outline.sections:
                sections.append(
                    ReportSection(
                        kind="findings",
                        title=outline_sec.title,
                        content=outline_sec.content,
                        claim_references=list(outline_sec.claim_ids)
                    )
                )
                
        # Gather references
        assessed_claims = [c.claim_id for c in assessment.claims]
        evidence_refs = list(set([cid for c in assessment.claims for cid in c.supported_by]))
        
        return ReportDocument(
            report_id=uuid4(),
            run_id=run_id,
            workspace_id=workspace_id,
            template_version=template,
            title=title,
            research_question=research_question,
            sections=sections,
            assessed_claim_references=assessed_claims,
            evidence_references=evidence_refs,
            created_at=datetime.now(timezone.utc)
        )
