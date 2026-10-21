import { useEffect, useMemo, useRef, useState } from 'react'
import { parseRunEventJson, reduceRunEvents } from '../../lib/api/runtime'
import type { RunEvent } from '../../lib/api/types'

const terminalEvents = new Set(['run.completed', 'run.partial', 'run.failed', 'run.cancelled'])
const MAX_ACTIVITY_EVENTS = 200
const MAX_SEEN_SEQUENCES = 500

interface StreamCallbacks {
  onEvent: (event: RunEvent) => void
  onConnected: (connected: boolean) => void
  onAuthExpired: () => void
}

// Fetch exposes HTTP auth errors and lets reconnects carry an explicit replay cursor.
export function startRunStream(runId: string, initialAfter: number, callbacks: StreamCallbacks) {
  const controller = new AbortController()
  let closed = false
  let cursor = Math.max(0, initialAfter)
  let retryTimer: ReturnType<typeof setTimeout> | undefined
  let releaseRetry: (() => void) | undefined
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  const close = () => {
    closed = true
    controller.abort()
    if (retryTimer) clearTimeout(retryTimer)
    releaseRetry?.()
    void reader?.cancel().catch(() => undefined)
  }
  const done = (async () => {
    let delay = 250
    while (!closed) {
      try {
        const response = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}/events?after=${cursor}`, {
          credentials: 'same-origin', signal: controller.signal,
          headers: { Accept: 'text/event-stream', 'Last-Event-ID': String(cursor) },
        })
        if (response.status === 401 || response.status === 403) {
          callbacks.onAuthExpired()
          close()
          return
        }
        if (!response.ok || !response.body) throw new Error('Event stream unavailable')
        callbacks.onConnected(true)
        reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (!closed) {
          const chunk = await reader.read()
          if (chunk.done) break
          buffer = (buffer + decoder.decode(chunk.value, { stream: true })).replace(/\r\n/g, '\n')
          if (buffer.length > 2_000_000) throw new Error('Event frame exceeds limit')
          let end: number
          while ((end = buffer.indexOf('\n\n')) >= 0) {
            const frame = buffer.slice(0, end)
            buffer = buffer.slice(end + 2)
            const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
            const event = data ? parseRunEventJson(data, runId) : null
            if (!event || event.seq <= cursor) continue
            cursor = event.seq
            delay = 250
            callbacks.onEvent(event)
            if (terminalEvents.has(event.event_type)) { close(); return }
          }
        }
      } catch {
        // Network/transport errors retry; authorization and cancellation stop above.
      } finally {
        callbacks.onConnected(false)
        await reader?.cancel().catch(() => undefined)
        reader = undefined
      }
      if (!closed) {
        await new Promise<void>(resolve => { releaseRetry = resolve; retryTimer = setTimeout(resolve, delay) })
        releaseRetry = undefined
        delay = Math.min(delay * 2, 10_000)
      }
    }
  })()
  return { close, done }
}

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

    const handle = (event: RunEvent) => {
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
        setConnected(false)
      }
    }

    const stream = startRunStream(runId, after, {
      onEvent: handle,
      onConnected: setConnected,
      onAuthExpired: () => window.dispatchEvent(new Event('ares:auth-expired')),
    })
    return () => { stream.close() }
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
