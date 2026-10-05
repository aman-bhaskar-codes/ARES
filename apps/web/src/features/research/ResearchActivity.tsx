import { CheckCircle2, CircleDot, LoaderCircle } from 'lucide-react'
import type { RunEvent, RunStatus } from '../../lib/api/types'

const stages: Array<[RunStatus, string]> = [
  ['planning', 'Planning'], ['discovering', 'Finding sources'], ['reading', 'Reading'],
  ['extracting', 'Extracting evidence'], ['checking', 'Checking support'], ['synthesizing', 'Writing answer']
]

const rank = new Map(stages.map(([stage], index) => [stage, index]))
const terminal = new Set<RunStatus>(['completed', 'partial', 'failed', 'cancelled'])

const eventLabels: Record<string, string> = {
  'run.created': 'Run admitted',
  'job.claimed': 'Worker accepted run',
  'run.resumed': 'Stored work resumed after worker restart',
  'run.status': 'Research stage changed',
  'plan.ready': 'Research plan prepared',
  'source.found': 'Source discovered',
  'source.read': 'Source read',
  'source.read_failed': 'Source could not be read',
  'evidence.added': 'Evidence preserved',
  'cache.hit': 'Reusable cached source used',
  'discovery.track_failed': 'One discovery track degraded',
  'semantic_checker.degraded': 'Semantic checker degraded',
  'semantic_checker.skipped': 'Semantic checker skipped',
  'provider.backoff': 'Provider asked ARES to back off',
  'run.checkpointed': 'Durable checkpoint saved',
  'answer.block.validated': 'Validated answer block published',
  'visualization.ready': 'Evidence-linked visual artifacts published',
  'visualization.failed': 'Visual artifact derivation degraded',
  'run.completed': 'Research completed',
  'run.partial': 'Research completed with gaps',
  'run.failed': 'Research failed',
  'run.cancelled': 'Research cancelled',
  'run.cancel.requested': 'Cancellation requested',
}

function safeDetail(event: RunEvent): string | null {
  const payload = event.payload
  if (event.event_type === 'source.found' && typeof payload.title === 'string') return payload.title.slice(0, 180)
  if (event.event_type === 'source.read' && typeof payload.title === 'string') return payload.title.slice(0, 180)
  if (event.event_type === 'provider.backoff' && typeof payload.provider === 'string') return `${payload.provider} provider`
  if (event.event_type === 'run.checkpointed' && typeof payload.step === 'string') return payload.step.replaceAll('_', ' ').slice(0, 120)
  if (event.event_type === 'run.status' && typeof payload.status === 'string') return payload.status.replaceAll('_', ' ')
  if (event.event_type === 'run.failed' && typeof payload.code === 'string') return payload.code.slice(0, 100)
  if (event.event_type === 'visualization.ready' && typeof payload.count === 'number') return `${payload.count} validated artifact${payload.count === 1 ? '' : 's'}`
  if (event.event_type === 'tool.unavailable' && typeof payload.tool === 'string') return `${payload.tool} unavailable`
  return null
}

export function ResearchActivity({ status, events, detailed = false }: { status: RunStatus; events: RunEvent[]; detailed?: boolean }) {
  if (terminal.has(status) && !detailed) return null
  const current = rank.get(status) ?? (terminal.has(status) ? stages.length : -1)
  const found = events.filter((event) => event.event_type === 'source.found').length
  const read = events.filter((event) => event.event_type === 'source.read').length
  const evidence = events.filter((event) => event.event_type === 'evidence.added').length
  const cached = events.filter((event) => event.event_type === 'cache.hit').length
  const degraded = events.filter((event) =>
    ['discovery.track_failed', 'semantic_checker.degraded', 'semantic_checker.skipped'].includes(event.event_type)
  ).length
  const visibleEvents = detailed
    ? events.filter((event) => eventLabels[event.event_type] || event.event_type.startsWith('run.')).slice(-200).reverse()
    : []

  return (
    <section className={`activity ${detailed ? 'activity-detailed' : ''}`} aria-live={detailed ? undefined : 'polite'} aria-label={detailed ? 'Research activity history' : 'Research progress'}>
      <div className="activity-head">
        {!terminal.has(status) && <span className="pulse-dot" />}
        <span>{terminal.has(status) ? 'Research activity' : 'ARES is researching'}</span>
        {(found > 0 || read > 0 || evidence > 0) && (
          <small>
            {found} found · {read} read · {evidence} evidence passages
            {cached > 0 ? ` · ${cached} cache reuse${cached === 1 ? '' : 's'}` : ''}
            {degraded > 0 ? ` · ${degraded} degraded step${degraded === 1 ? '' : 's'}` : ''}
          </small>
        )}
      </div>
      <div className="activity-stages">
        {stages.map(([stage, label], index) => (
          <div className={`stage ${index === current && !terminal.has(status) ? 'active' : ''}`} key={stage}>
            {index < current || terminal.has(status) ? <CheckCircle2 size={15} /> : index === current ? <LoaderCircle className="spin" size={15} /> : <CircleDot size={15} />}
            <span>{label}</span>
          </div>
        ))}
      </div>
      {detailed && (
        <div className="activity-log">
          <div className="activity-log-note">User-safe operational events only. ARES does not expose hidden chain-of-thought or model scratch work.</div>
          {visibleEvents.length ? <ol>{visibleEvents.map((event) => {
            const detail = safeDetail(event)
            return <li data-run-event key={`${event.seq}-${event.event_type}`}>
              <time dateTime={event.at}>{new Date(event.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>
              <span><strong>{eventLabels[event.event_type] ?? event.event_type.replaceAll('.', ' ')}</strong>{detail && <small>{detail}</small>}</span>
              <code>#{event.seq}</code>
            </li>
          })}</ol> : <div className="workspace-empty">No persisted user-safe activity events are available in this replay window.</div>}
        </div>
      )}
    </section>
  )
}
