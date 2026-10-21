import { ArrowRight, LoaderCircle } from 'lucide-react'
import type { RunEvent, RunStatus } from '../../lib/api/types'

const labels: Partial<Record<RunStatus, string>> = {
  planning: 'Planning your search', discovering: 'Finding sources', reading: 'Reading sources',
  extracting: 'Collecting evidence', checking: 'Checking sources', synthesizing: 'Writing your answer',
}
const terminal = new Set<RunStatus>(['completed', 'partial', 'failed', 'cancelled'])

export function CompactResearchProgress({ status, events, onViewActivity }: { status: RunStatus; events: RunEvent[]; onViewActivity: () => void }) {
  if (terminal.has(status)) return null
  const found = events.filter((event) => event.event_type === 'source.found').length
  return <section className="compact-research-progress" aria-live="polite" aria-label="Research progress">
    <LoaderCircle className="spin" size={17} />
    <span>{labels[status] ?? 'Starting your research'}{found > 0 && <small>{found} sources found</small>}</span>
    <button className="quiet-button" onClick={onViewActivity}>View activity <ArrowRight size={14}/></button>
  </section>
}
