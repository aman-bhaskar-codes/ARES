import { afterEach, expect, it, vi } from 'vitest'
import { startRunStream } from './useRunStream'

const event = (seq: number, type = 'run.status') => ({ schema_version: 2, run_id: 'run-1', seq, event_type: type, at: '2026-10-14T00:00:00Z', payload: {} })
const response = (seq: number, type?: string) => new Response(`data: ${JSON.stringify(event(seq, type))}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it('reconnects using the last validated sequence as Last-Event-ID', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn().mockResolvedValueOnce(response(8)).mockResolvedValueOnce(response(9, 'run.completed'))
  vi.stubGlobal('fetch', fetcher)
  const seen: number[] = []
  const stream = startRunStream('run-1', 7, { onEvent: e => seen.push(e.seq), onConnected: vi.fn(), onAuthExpired: vi.fn() })
  await vi.advanceTimersByTimeAsync(500)
  await stream.done
  expect(seen).toEqual([8, 9])
  expect(new Headers(fetcher.mock.calls[0][1].headers).get('Last-Event-ID')).toBe('7')
  expect(new Headers(fetcher.mock.calls[1][1].headers).get('Last-Event-ID')).toBe('8')
})

it('stops reconnecting and reports an expired session on 401', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('', { status: 401 }))
  vi.stubGlobal('fetch', fetcher)
  const expired = vi.fn()
  const stream = startRunStream('run-1', 0, { onEvent: vi.fn(), onConnected: vi.fn(), onAuthExpired: expired })
  await stream.done
  expect(expired).toHaveBeenCalledOnce()
  expect(fetcher).toHaveBeenCalledOnce()
})
