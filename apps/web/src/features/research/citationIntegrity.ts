import type { AnswerBlock, CitationRef } from '../../lib/api/types'

export function indexCitations(block: AnswerBlock): Map<number, CitationRef> {
  const byLabel = new Map(block.citations.map((citation) => [citation.label, citation]))
  for (const claim of block.claims) {
    for (const label of claim.citation_labels) {
      if (!byLabel.has(label)) throw new Error(`Answer claim references missing citation label ${label}`)
    }
  }
  return byLabel
}
