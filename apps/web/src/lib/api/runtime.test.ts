import { describe, expect, it } from 'vitest'
import { parseAuthMe, parseRunEventJson, parseRunSnapshot, reduceRunEvents } from './runtime'

const event = (seq: number, event_type = 'future.additive') => ({ schema_version: 2, run_id: 'run-1', seq, event_type, at: '2026-10-03T00:00:00Z', payload: {} })

describe('run event boundary', () => {
  it('accepts unknown additive event names at a supported schema version', () => expect(parseRunEventJson(JSON.stringify(event(1)), 'run-1')?.event_type).toBe('future.additive'))
  it('rejects malformed, future-schema, and wrong-run events', () => {
    expect(parseRunEventJson('{')).toBeNull()
    expect(parseRunEventJson(JSON.stringify({ ...event(1), schema_version: 99 }))).toBeNull()
    expect(parseRunEventJson(JSON.stringify(event(1)), 'other')).toBeNull()
  })
  it('deduplicates, orders, and bounds activity', () => {
    let items = reduceRunEvents([], event(3), 2)
    items = reduceRunEvents(items, event(1), 2)
    items = reduceRunEvents(items, event(3, 'replacement'), 2)
    items = reduceRunEvents(items, event(4), 2)
    expect(items.map((item) => item.seq)).toEqual([3,4])
    expect(items[0].event_type).toBe('replacement')
  })
  it('replays more than 200 events without unbounded activity growth', () => {
    let items = [] as ReturnType<typeof reduceRunEvents>
    for (let seq = 1; seq <= 240; seq += 1) items = reduceRunEvents(items, event(seq), 200)
    expect(items).toHaveLength(200)
    expect(items[0].seq).toBe(41)
    expect(items.at(-1)?.seq).toBe(240)
  })
})

describe('API runtime validators', () => {
  it('normalizes legacy-compatible run defaults while validating core fields', () => {
    const run = parseRunSnapshot({
      id: 'run-1', conversation_id: 'conversation-1', query: 'question', mode: 'quick', status: 'queued',
      created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z',
    })
    expect(run.budget_version).toBe('legacy')
    expect(run.last_seq).toBe(0)
    expect(run.answer_blocks).toEqual([])
    expect(run.source_scope).toEqual([])
  })

  it('preserves the selected provider and rejects unknown model IDs', () => {
    const value = { id: 'run-1', conversation_id: 'conversation-1', query: 'question', mode: 'quick', status: 'queued', created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z' }
    expect(parseRunSnapshot({...value, model_provider: 'gemini'}).model_provider).toBe('gemini')
    expect(parseRunSnapshot({...value, model_provider: 'qwen'}).model_provider).toBe('qwen')
    expect(() => parseRunSnapshot({...value, model_provider: 'unknown'})).toThrow()
  })

  it('rejects invalid run enums and malformed auth responses', () => {
    expect(() => parseRunSnapshot({
      id: 'run-1', conversation_id: 'conversation-1', query: 'question', mode: 'unknown', status: 'queued',
      created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z',
    })).toThrow()
    expect(() => parseAuthMe({ auth_mode: 'oidc', role: 'owner', csrf_required: true })).toThrow()
  })

  it('accepts a valid auth response', () => {
    const auth = parseAuthMe({
      user_id: 'u1', workspace_id: 'w1', subject: 'sub', email: null, display_name: 'Researcher',
      role: 'owner', auth_mode: 'oidc', csrf_required: true,
    })
    expect(auth.workspace_id).toBe('w1')
  })
})
