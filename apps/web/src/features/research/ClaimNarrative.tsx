import { indexCitations } from './citationIntegrity'
import type { AnswerBlock } from '../../lib/api/types'
import { CitationChip } from './CitationChip'

export function ClaimNarrative({ block, onEvidence }: { block: AnswerBlock; onEvidence: (id: string, trigger?: HTMLElement) => void }) {
  const byLabel = indexCitations(block)
  
  return (
    <div className="answer-prose claim-narrative">
      {block.claims.map((claim, index) => {
        const isSupported = claim.support_status === 'supported' && claim.assessment_state === 'semantic_assessed'
        return (
          <p key={`${claim.text}-${index}`} className={isSupported ? '' : `claim-exception claim-${claim.support_status}`}>
            {!isSupported && (
               <span className="claim-status-inline">
                 {claim.assessment_state !== 'semantic_assessed' ? 'SEMANTIC SUPPORT UNASSESSED' : 
                  claim.support_status === 'partially_supported' ? 'PARTLY SUPPORTED' :
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
