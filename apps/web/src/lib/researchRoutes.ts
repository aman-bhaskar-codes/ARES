export const researchViews = ['answer', 'sources', 'compare', 'diagnostics', 'activity'] as const
export type ResearchView = (typeof researchViews)[number]

const researchViewSet = new Set<string>(researchViews)

export interface ResearchLocation {
  conversationId?: string
  runId?: string
  evidenceId?: string
  view: ResearchView
}

function decodeSegment(value: string | undefined): string | undefined {
  if (!value) return undefined
  try {
    const decoded = decodeURIComponent(value)
    return decoded && !decoded.includes('/') ? decoded : undefined
  } catch {
    return undefined
  }
}

function viewFromSearch(search: string): ResearchView {
  const requested = new URLSearchParams(search).get('view')
  return requested && researchViewSet.has(requested) ? requested as ResearchView : 'answer'
}

/** Parse only the stable ARES research route shapes; malformed/extra segments are ignored. */
export function parseResearchLocation(pathname: string, search = ''): ResearchLocation {
  const view = viewFromSearch(search)
  const parts = pathname.split('/').filter(Boolean)
  if (parts[0] !== 'research') return { view }

  if (parts.length === 2) {
    const conversationId = decodeSegment(parts[1])
    return conversationId ? { conversationId, view } : { view }
  }
  if (parts.length === 4 && parts[2] === 'runs') {
    const conversationId = decodeSegment(parts[1])
    const runId = decodeSegment(parts[3])
    return conversationId && runId ? { conversationId, runId, view } : { view }
  }
  if (parts.length === 6 && parts[2] === 'runs' && parts[4] === 'evidence') {
    const conversationId = decodeSegment(parts[1])
    const runId = decodeSegment(parts[3])
    const evidenceId = decodeSegment(parts[5])
    return conversationId && runId && evidenceId ? { conversationId, runId, evidenceId, view } : { view }
  }
  return { view }
}

function segment(value: string): string {
  if (!value || value.includes('/')) throw new TypeError('Research route identifiers must be non-empty path segments')
  return encodeURIComponent(value)
}

function withView(path: string, view: ResearchView): string {
  return `${path}?view=${encodeURIComponent(view)}`
}

export function researchConversationUrl(conversationId: string, view: ResearchView = 'answer'): string {
  return withView(`/research/${segment(conversationId)}`, view)
}

export function researchRunUrl(
  conversationId: string,
  runId: string,
  view: ResearchView = 'answer',
  evidenceId?: string,
): string {
  const base = `/research/${segment(conversationId)}/runs/${segment(runId)}`
  return withView(evidenceId ? `${base}/evidence/${segment(evidenceId)}` : base, view)
}
