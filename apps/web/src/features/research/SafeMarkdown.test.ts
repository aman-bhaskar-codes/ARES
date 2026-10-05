import { describe, expect, it, vi } from 'vitest'

vi.stubGlobal('window', { location: { origin: 'https://ares.example' } })
import { safeMarkdownUrl } from './SafeMarkdown'

describe('safeMarkdownUrl', () => {
  it('allows same-origin paths and normal web links', () => {
    expect(safeMarkdownUrl('/research/run')).toBe('/research/run')
    expect(safeMarkdownUrl('https://example.com/a')).toBe('https://example.com/a')
    expect(safeMarkdownUrl('//example.com/a')).toBe('//example.com/a')
  })

  it('rejects executable or embedded data URLs', () => {
    expect(safeMarkdownUrl('javascript:alert(1)')).toBe('')
    expect(safeMarkdownUrl('data:text/html,<script>alert(1)</script>')).toBe('')
  })
})
