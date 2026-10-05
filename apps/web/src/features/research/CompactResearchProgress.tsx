import { CheckCircle2, CircleDot, LoaderCircle, AlertTriangle } from 'lucide-react'
import type { RunEvent, RunStatus } from '../../lib/api/types'

const stages: Array<[RunStatus, string]> = [
  ['planning', 'Planning'], ['discovering', 'Sources'], ['reading', 'Reading'],
  ['extracting', 'Evidence'], ['checking', 'Checking'], ['synthesizing', 'Writing']
]

const rank = new Map(stages.map(([stage], index) => [stage, index]))
const terminal = new Set<RunStatus>(['completed', 'partial', 'failed', 'cancelled'])

export function CompactResearchProgress({ status, events, onViewActivity }: { status: RunStatus; events: RunEvent[]; onViewActivity: () => void }) {
  if (terminal.has(status)) return null
  const current = rank.get(status) ?? -1
  
  const found = events.filter((event) => event.event_type === 'source.found').length
  const read = events.filter((event) => event.event_type === 'source.read').length
  const evidence = events.filter((event) => event.event_type === 'evidence.added').length
  const degraded = events.filter((event) =>
    ['discovery.track_failed', 'semantic_checker.degraded', 'semantic_checker.skipped', 'provider.backoff'].includes(event.event_type)
  ).length

  return (
    <section className="compact-research-progress" aria-live="polite" aria-label="Research progress" style={{ marginBottom: '24px', padding: '16px', background: 'var(--surface-sunken)', borderRadius: '8px' }}>
      <div className="progress-header" style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
        <div className="progress-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
          <span className="pulse-dot" />
          <span>ARES is researching</span>
        </div>
        {(found > 0 || read > 0 || evidence > 0) && (
          <div className="progress-stats" style={{ color: 'var(--ink-light)', fontSize: '13px' }}>
            {found} found · {read} read · {evidence} evidence passages
          </div>
        )}
      </div>

      <div className="activity-stages" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {stages.map(([stage, label], index) => (
          <div className={`stage ${index === current ? 'active' : ''}`} key={stage} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', color: index <= current ? 'var(--ink)' : 'var(--ink-lighter)' }}>
            {index < current ? <CheckCircle2 size={14} /> : index === current ? <LoaderCircle className="spin" size={14} /> : <CircleDot size={14} />}
            <span>{label}</span>
            {index < stages.length - 1 && <span style={{ color: 'var(--line)', margin: '0 4px' }}>—</span>}
          </div>
        ))}
      </div>

      {degraded > 0 && (
        <div className="progress-degraded" style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--amber-11)' }}>
          <AlertTriangle size={14} /> {degraded} research step{degraded === 1 ? '' : 's'} degraded.{' '}
          <button className="quiet-button" style={{ color: 'var(--amber-11)', textDecoration: 'underline', padding: 0 }} onClick={onViewActivity}>View Activity</button>
        </div>
      )}
    </section>
  )
}
