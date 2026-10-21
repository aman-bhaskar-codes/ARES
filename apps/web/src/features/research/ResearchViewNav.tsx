import { BookOpenText, ListTree, GitCompareArrows, Activity, Gauge } from 'lucide-react'
import type { ResearchView } from '../../lib/researchRoutes'

interface ResearchViewNavProps {
  activeView: ResearchView
  onSelectView: (view: ResearchView) => void
  evidenceCount?: number
}

export function ResearchViewNav({
  activeView,
  onSelectView,
  evidenceCount
}: ResearchViewNavProps) {
  return (
    <nav className="research-tabs" aria-label="Research workspace views">
      <button aria-current={activeView === 'answer' ? 'page' : undefined} className={activeView === 'answer' ? 'active' : ''} onClick={() => onSelectView('answer')}>
        <BookOpenText size={15} /> Answer
      </button>
      <button aria-current={activeView === 'sources' ? 'page' : undefined} className={activeView === 'sources' ? 'active' : ''} onClick={() => onSelectView('sources')}>
        <ListTree size={15} /> Sources {evidenceCount ? <span>{evidenceCount}</span> : null}
      </button>
      <button aria-current={activeView === 'compare' ? 'page' : undefined} className={activeView === 'compare' ? 'active' : ''} onClick={() => onSelectView('compare')}>
        <GitCompareArrows size={15} /> Compare
      </button>
      <button aria-current={activeView === 'diagnostics' ? 'page' : undefined} className={activeView === 'diagnostics' ? 'active' : ''} onClick={() => onSelectView('diagnostics')}>
        <Gauge size={15} /> Diagnostics
      </button>
      <button aria-current={activeView === 'activity' ? 'page' : undefined} className={activeView === 'activity' ? 'active' : ''} onClick={() => onSelectView('activity')}>
        <Activity size={15} /> Activity
      </button>
    </nav>
  )
}
