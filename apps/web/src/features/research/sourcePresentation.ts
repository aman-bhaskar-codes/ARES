import type { Evidence, SourceScope } from '../../lib/api/types'

export interface EvidenceSourceGroup {
  sourceId: string
  title: string
  domain: string
  kind: SourceScope
  publishedAt: string | null
  readState: 'full' | 'snippet_only' | 'blocked'
  evidence: Evidence[]
}

export function groupEvidenceBySource(evidence: Evidence[]): EvidenceSourceGroup[] {
  const map = new Map<string, EvidenceSourceGroup>()
  
  for (const item of evidence) {
    const sourceId = item.source.id
    if (!map.has(sourceId)) {
      map.set(sourceId, {
        sourceId,
        title: item.source.title,
        domain: item.source.domain,
        kind: item.source.source_kind as SourceScope,
        publishedAt: item.source.published_at ?? null,
        readState: item.source.read_state ?? 'full',
        evidence: []
      })
    }
    map.get(sourceId)!.evidence.push(item)
  }
  
  return Array.from(map.values())
}
