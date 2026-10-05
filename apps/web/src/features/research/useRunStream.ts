import { useEffect, useMemo, useRef, useState } from 'react'
import { parseRunEventJson, reduceRunEvents } from '../../lib/api/runtime'
import type { RunEvent } from '../../lib/api/types'

const terminalEvents = new Set(['run.completed', 'run.partial', 'run.failed', 'run.cancelled'])
const MAX_ACTIVITY_EVENTS = 200
const MAX_SEEN_SEQUENCES = 500

// M06 emitted named SSE events. M07 additionally emits a generic copy so additive
// event types do not disappear in older fixed registries. Listening to both keeps
// the hook compatible during a rolling frontend/backend upgrade; sequence de-dupe
// guarantees one logical activity record.
const legacyEventTypes = [
  'run.created', 'job.claimed', 'run.resumed', 'run.status', 'run.completed', 'run.partial',
  'run.failed', 'run.cancelled', 'plan.ready', 'route.decided', 'source.found',
  'source.read_failed', 'sources.deduplicated', 'security.content_risk', 'evidence.added',
  'retrieval.network', 'retrieval.documents', 'coverage.updated', 'claim.checked',
  'cache.hit', 'discovery.track_failed', 'provider.backoff', 'semantic_checker.skipped',
  'semantic_checker.degraded', 'browser.fallback', 'answer.block.validated',
  'stage.timing', 'answer.block', 'run.checkpointed', 'run.checkpoint.restored',
]

export function useRunStream(runId: string | undefined, initialAfter = 0) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [snapshotRequiredSeq, setSnapshotRequiredSeq] = useState<number>()
  const seen = useRef(new Set<number>())
  const expected = useRef(0)

  useEffect(() => {
    setEvents([])
    setConnected(false)
    setSnapshotRequiredSeq(undefined)
    seen.current = new Set()
    const after = Math.max(0, Number.isInteger(initialAfter) ? initialAfter : 0)
    expected.current = after
    if (!runId) return

    const source = new EventSource(`/api/v1/runs/${runId}/events?after=${after}`)
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)

    const handle = (message: MessageEvent<string>) => {
      const event = parseRunEventJson(message.data, runId)
      if (!event || seen.current.has(event.seq)) return
      if (event.seq > expected.current + 1 && event.event_type !== 'stream.snapshot_required') {
        setSnapshotRequiredSeq(event.seq)
      }
      expected.current = Math.max(expected.current, event.seq)
      seen.current.add(event.seq)
      if (seen.current.size > MAX_SEEN_SEQUENCES) {
        const ordered = [...seen.current].sort((a, b) => a - b)
        seen.current = new Set(ordered.slice(-MAX_SEEN_SEQUENCES))
      }
      if (event.event_type === 'stream.snapshot_required') setSnapshotRequiredSeq(event.seq)
      setEvents((current) => reduceRunEvents(current, event, MAX_ACTIVITY_EVENTS))
      if (terminalEvents.has(event.event_type)) {
        source.close()
        setConnected(false)
      }
    }

    source.onmessage = handle
    for (const eventType of legacyEventTypes) source.addEventListener(eventType, handle as EventListener)
    return () => {
      for (const eventType of legacyEventTypes) source.removeEventListener(eventType, handle as EventListener)
      source.close()
      setConnected(false)
    }
    // initialAfter seeds the first connection for a run. Snapshot polling may advance
    // last_seq without creating EventSource reconnect churn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const latestStage = useMemo(() => {
    const stage = [...events].reverse().find((event) => event.event_type === 'run.status')
    return typeof stage?.payload.status === 'string' ? stage.payload.status : undefined
  }, [events])

  return { events, connected, latestStage, snapshotRequiredSeq }
}
