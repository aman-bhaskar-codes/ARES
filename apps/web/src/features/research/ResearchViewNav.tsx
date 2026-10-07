import { BookOpenText, ListTree, GitCompareArrows, Sparkles, ChartNoAxesCombined } from 'lucide-react'
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
      <button className={activeView === 'answer' ? 'active' : ''} onClick={() => onSelectView('answer')}>
        <BookOpenText size={15} /> Answer
      </button>
      <button className={activeView === 'sources' ? 'active' : ''} onClick={() => onSelectView('sources')}>
        <ListTree size={15} /> Sources {evidenceCount ? <span>{evidenceCount}</span> : null}
      </button>
      <button className={activeView === 'compare' ? 'active' : ''} onClick={() => onSelectView('compare')}>
        <GitCompareArrows size={15} /> Compare
      </button>
      <button className={activeView === 'diagnostics' ? 'active' : ''} onClick={() => onSelectView('diagnostics')}>
        <ChartNoAxesCombined size={15} /> Diagnostics
      </button>
      <button className={activeView === 'activity' ? 'active' : ''} onClick={() => onSelectView('activity')}>
        <Sparkles size={15} /> Activity
      </button>
    </nav>
  )
}
