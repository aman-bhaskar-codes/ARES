import { Copy } from 'lucide-react'
import type { AnswerBlock, Evidence } from '../../lib/api/types'
import { SafeMarkdown } from './SafeMarkdown'
import { answerPresentationMode, buildCitedAnswerText } from './answerPresentation'
import { CitationChip } from './CitationChip'
import { ClaimNarrative } from './ClaimNarrative'
import { AnswerEvidenceSummary } from './AnswerEvidenceSummary'

export function Answer({ 
  block, 
  runEvidence,
  onEvidence,
  onReviewSources 
}: { 
  block: AnswerBlock
  runEvidence?: Evidence[]
  onEvidence: (id: string, trigger?: HTMLElement) => void
  onReviewSources: () => void 
}) {
  const mode = answerPresentationMode(block)

  return (
    <article className="answer-card">
      <div className="answer-toolbar">
        <span className="answer-label">Answer</span>
        <button
          className="quiet-button"
          onClick={() => navigator.clipboard.writeText(buildCitedAnswerText(block))}
        >
          <Copy size={15} /> Copy
        </button>
      </div>

      {block.claims?.some((claim) => claim.assessment_state !== 'semantic_assessed') && (
        <p className="answer-verification-note">Based on retrieved sources. AI semantic verification has not been performed; review the citations for important details.</p>
      )}

      {mode === 'empty'  && (
        <div className="answer-prose">
          <p className="claim-status">No claims or answer content available.</p>
        </div>
      )}

      {mode === 'rich_markdown' && (
        <>
          <div className="answer-prose"><SafeMarkdown markdown={block.markdown} /></div>
          {block.claims && block.claims.length > 0 && (
            <div style={{ marginTop: '20px' }}>
              <div className="answer-label" style={{ marginBottom: '8px' }}>Claims Audited</div>
              <ClaimNarrative block={block} onEvidence={onEvidence} />
            </div>
          )}
        </>
      )}

      {mode === 'claim_narrative' && (
        <ClaimNarrative block={block} onEvidence={onEvidence} />
      )}

      {!block.claims?.length && block.citations.length > 0 && <div className="citation-row" aria-label="Retrieved evidence citations">
        {block.citations.map((citation) => <CitationChip key={citation.evidence_id} label={citation.label} evidenceId={citation.evidence_id} onOpen={onEvidence} />)}
      </div>}

      <AnswerEvidenceSummary 
        block={block} 
        runEvidence={runEvidence} 
        onReviewSources={onReviewSources} 
      />
    </article>
  )
}
