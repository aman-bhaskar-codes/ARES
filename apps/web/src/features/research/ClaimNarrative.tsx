import { indexCitations } from './citationIntegrity'
import type { AnswerBlock } from '../../lib/api/types'
import { CitationChip } from './CitationChip'

export function ClaimNarrative({ block, onEvidence }: { block: AnswerBlock; onEvidence: (id: string, trigger?: HTMLElement) => void }) {
  const byLabel = indexCitations(block)
  
  return (
    <div className="answer-prose claim-narrative">
      {block.claims.map((claim, index) => {
        const hasSemanticException = claim.assessment_state === 'semantic_assessed' && claim.support_status !== 'supported'
        return (
          <p key={`${claim.text}-${index}`} className={hasSemanticException ? `claim-exception claim-${claim.support_status}` : ''}>
            {hasSemanticException && (
               <span className="claim-status-inline">
                 {claim.support_status === 'partially_supported' ? 'PARTLY SUPPORTED' :
                  claim.support_status === 'conflicting' ? 'SOURCES DISAGREE' : 'EVIDENCE INCOMPLETE'}
               </span>
            )}
            {claim.text}{' '}
            <span className="inline-citations">
              {claim.citation_labels.map((label) => {
                const citation = byLabel.get(label)
                if (!citation) return null
                return (
                  <CitationChip
                    key={label}
                    label={label}
                    evidenceId={citation.evidence_id}
                    onOpen={onEvidence}
                  />
                )
              })}
            </span>
          </p>
        )
      })}
    </div>
  )
}
