import { Copy } from 'lucide-react'
import type { AnswerBlock, SupportStatus } from '../../lib/api/types'
import { indexCitations } from './citationIntegrity'
import { SafeMarkdown } from './SafeMarkdown'

const statusLabel: Record<SupportStatus, string> = {
  supported: 'Supported',
  partially_supported: 'Partly supported',
  conflicting: 'Sources disagree',
  insufficient_evidence: 'Not enough evidence',
}

export function Answer({ block, onEvidence }: { block: AnswerBlock; onEvidence: (id: string) => void }) {
  const byLabel = indexCitations(block)
  return (
    <article className="answer-card">
      <div className="answer-toolbar">
        <span className="answer-label">Answer</span>
        <button
          className="quiet-button"
          onClick={() => navigator.clipboard.writeText([
            block.markdown,
            ...block.claims.map((claim) => `${claim.text} ${claim.citation_labels.map((label) => `[${label}]`).join(' ')}`)
          ].join('\n\n'))}
        >
          <Copy size={15} /> Copy
        </button>
      </div>
      <div className="answer-prose"><SafeMarkdown markdown={block.markdown} /></div>
      {block.claims.length > 0 && (
        <div className="claim-list" aria-label="Evidence-backed claims">
          {block.claims.map((claim, index) => (
            <div key={`${claim.text}-${index}`} className={`answer-claim claim-${claim.support_status}`}>
              <div className="claim-status">{statusLabel[claim.support_status]}</div>
              {claim.assessment_state !== 'semantic_assessed' && (
                <div className="claim-assessment">Evidence linked; semantic support not yet established.</div>
              )}
              <p>
                <span>{claim.text}</span>{' '}
                <span className="inline-citations">
                  {claim.citation_labels.map((label) => {
                    const citation = byLabel.get(label)
                    return citation ? (
                      <button
                        key={label}
                        className="citation-button"
                        aria-label={`Open evidence source ${label}`}
                        onClick={() => onEvidence(citation.evidence_id)}
                      >
                        {label}
                      </button>
                    ) : null
                  })}
                </span>
              </p>
            </div>
          ))}
        </div>
      )}
    </article>
  )
}
