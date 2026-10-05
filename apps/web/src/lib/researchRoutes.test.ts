import { describe, expect, it } from 'vitest'
import { parseResearchLocation, researchConversationUrl, researchRunUrl } from './researchRoutes'

describe('stable research routes', () => {
  it('round-trips a run evidence deep link and selected view', () => {
    const url = researchRunUrl('conversation 1', 'run #2', 'compare', 'evidence #7')
    const [pathname, search] = url.split('?')
    expect(url).toBe('/research/conversation%201/runs/run%20%232/evidence/evidence%20%237?view=compare')
    expect(parseResearchLocation(pathname, `?${search}`)).toEqual({
      conversationId: 'conversation 1', runId: 'run #2', evidenceId: 'evidence #7', view: 'compare',
    })
  })

  it('does not build ambiguous identifiers containing path separators', () => {
    expect(() => researchRunUrl('c1', 'run/hidden')).toThrow(TypeError)
  })

  it('parses the canonical run route', () => {
    expect(parseResearchLocation('/research/c1/runs/r1', '?view=sources')).toEqual({
      conversationId: 'c1', runId: 'r1', view: 'sources',
    })
  })

  it('falls back to answer for an unknown view', () => {
    expect(parseResearchLocation('/research/c1', '?view=admin')).toEqual({ conversationId: 'c1', view: 'answer' })
  })

  it('rejects extra or malformed route shapes', () => {
    expect(parseResearchLocation('/research/c1/runs/r1/evidence/e1/extra', '?view=activity')).toEqual({ view: 'activity' })
    expect(parseResearchLocation('/research/%E0%A4%A/runs/r1')).toEqual({ view: 'answer' })
  })

  it('builds a canonical conversation URL', () => {
    expect(researchConversationUrl('thread #1', 'activity')).toBe('/research/thread%20%231?view=activity')
  })
})
