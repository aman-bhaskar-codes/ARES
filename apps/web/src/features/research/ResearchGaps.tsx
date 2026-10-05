import { useState } from 'react'
import { Info, ChevronDown, ChevronUp } from 'lucide-react'

export function ResearchGaps({ gaps, runStatus }: { gaps: string[]; runStatus: string }) {
  const [showAll, setShowAll] = useState(false)

  if (!gaps || gaps.length === 0) return null

  const isPartial = runStatus === 'partial'
  const displayLimit = 2
  const hasMore = gaps.length > displayLimit
  const displayedGaps = showAll ? gaps : gaps.slice(0, displayLimit)

  return (
    <section className={`gap-card ${isPartial ? 'gap-card-prominent' : ''}`}>
      <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
        <Info size={18} style={{ marginTop: '2px' }} />
        <div className="gap-content">
          <strong>What remains uncertain</strong>
          <div className="gap-list" style={{ marginTop: '8px' }}>
            {displayedGaps.map((gap, idx) => (
              <p key={idx} style={{ margin: '4px 0' }}>{gap}</p>
            ))}
          </div>
          {hasMore && (
            <button 
              className="quiet-button gap-toggle" 
              onClick={() => setShowAll(!showAll)}
              style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              {showAll ? <><ChevronUp size={14} /> Show fewer</> : <><ChevronDown size={14} /> Show all {gaps.length}</>}
            </button>
          )}
        </div>
      </div>
    </section>
  )
}
