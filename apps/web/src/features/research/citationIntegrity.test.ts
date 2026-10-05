import { describe, expect, it } from 'vitest'
import type { AnswerBlock } from '../../lib/api/types'
import { indexCitations } from './citationIntegrity'

const block = (label: number): AnswerBlock => ({
  id: 'answer-1',
  markdown: 'summary',
  citations: [{ evidence_id: '00000000-0000-0000-0000-000000000001', label: 1 }],
  claims: [{ text: 'Evidence-backed claim', citation_labels: [label], support_status: 'supported', checker_method: 'fixture', checker_version: '1', assessment_state: 'semantic_assessed', assessment_rationale: 'fixture support' }],
  finalized: true,
})

describe('claim citation integrity', () => {
  it('indexes server citations for claim rendering', () => {
    expect(indexCitations(block(1)).get(1)?.evidence_id).toContain('0001')
  })

  it('rejects a claim whose citation label is absent', () => {
    expect(() => indexCitations(block(2))).toThrow('missing citation label 2')
  })
})
