import { summarizeAnswerSupport } from './answerPresentation'
import type { AnswerBlock, Evidence } from '../../lib/api/types'
import { ListTree } from 'lucide-react'

interface AnswerEvidenceSummaryProps {
  block: AnswerBlock
  runEvidence?: Evidence[]
  onReviewSources: () => void
}

export function AnswerEvidenceSummary({ block, runEvidence, onReviewSources }: AnswerEvidenceSummaryProps) {
  if (!block.claims || block.claims.length === 0) return null

  const summary = summarizeAnswerSupport(block.claims)
  
  let distinctSourcesText = ''
  if (runEvidence && runEvidence.length > 0) {
    const sources = new Set(runEvidence.map(e => e.source?.id || e.id)) // Fallback to id if source.id isn't present
    distinctSourcesText = ` · ${sources.size} distinct source${sources.size === 1 ? '' : 's'}`
  }

  return (
    <div className="export-bar" aria-label="Evidence Summary">
      <div style={{ flex: 1 }}>
        <span style={{ color: 'var(--ink)', fontWeight: 750, display: 'block', fontSize: '12px' }}>
          Evidence used
        </span>
        <span style={{ display: 'block', marginTop: '4px' }}>
          {block.citations?.length || 0} evidence passage{block.citations?.length === 1 ? '' : 's'}{distinctSourcesText}
        </span>
        <div style={{ display: 'flex', gap: '12px', marginTop: '8px', color: 'var(--ink)' }}>
          {summary.supported > 0 && <div><strong>{summary.supported}</strong> supported</div>}
          {summary.partiallySupported > 0 && <div><strong>{summary.partiallySupported}</strong> partly supported</div>}
          {summary.conflicting > 0 && <div><strong>{summary.conflicting}</strong> sources disagree</div>}
          {summary.insufficient > 0 && <div><strong>{summary.insufficient}</strong> insufficient</div>}
        </div>
      </div>
      <button onClick={onReviewSources}>
        <ListTree size={14} /> Review sources
      </button>
    </div>
  )
}
