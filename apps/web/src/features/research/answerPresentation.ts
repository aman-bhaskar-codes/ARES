import type { AnswerBlock, AnswerClaim } from '../../lib/api/types'

export type AnswerPresentationMode = 'claim_narrative' | 'rich_markdown' | 'empty'

export interface AnswerSupportSummary {
  total: number
  supported: number
  partiallySupported: number
  conflicting: number
  insufficient: number
  semanticUnassessed: number
}

export function answerPresentationMode(block: AnswerBlock): AnswerPresentationMode {
  if (!block.claims?.length && (!block.markdown || !block.markdown.trim())) {
    return 'empty'
  }

  if (block.claims?.length && block.markdown) {
    // Normalization test to see if markdown is basically just the claims appended together
    const mdText = block.markdown.replace(/^#+ .*$/gm, '').replace(/\s+/g, ' ').trim()
    const claimsText = block.claims.map(c => c.text).join(' ').replace(/\s+/g, ' ').trim()
    
    // If the markdown is just the claims appended together (plus maybe a heading), 
    // it's a claim_narrative.
    if (mdText === claimsText || mdText.includes(claimsText)) {
      return 'claim_narrative'
    }
  }

  if (block.claims?.length && !block.markdown) {
    return 'claim_narrative'
  }

  return 'rich_markdown'
}

export function summarizeAnswerSupport(claims: AnswerClaim[]): AnswerSupportSummary {
  const summary: AnswerSupportSummary = {
    total: claims.length,
    supported: 0,
    partiallySupported: 0,
    conflicting: 0,
    insufficient: 0,
    semanticUnassessed: 0
  }

  for (const claim of claims) {
    if (claim.assessment_state !== 'semantic_assessed') {
       summary.semanticUnassessed++
       continue
    }

    switch (claim.support_status) {
      case 'supported':
        summary.supported++
        break
      case 'partially_supported':
        summary.partiallySupported++
        break
      case 'conflicting':
        summary.conflicting++
        break
      case 'insufficient_evidence':
        summary.insufficient++
        break
      default:
        break
    }
  }

  return summary
}

export function buildCitedAnswerText(block: AnswerBlock): string {
  if (!block.claims || block.claims.length === 0) {
    return block.markdown || ''
  }

  const mode = answerPresentationMode(block)
  if (mode === 'rich_markdown') {
    return [
      block.markdown,
      ...block.claims.map((claim) => `${claim.text} ${claim.citation_labels.map((label) => `[${label}]`).join(' ')}`)
    ].join('\n\n')
  }

  // mode === 'claim_narrative'
  return block.claims.map((claim) => {
    let text = claim.text
    if (claim.citation_labels && claim.citation_labels.length > 0) {
      const citeStr = claim.citation_labels.map(l => `[${l}]`).join(' ')
      text += ` ${citeStr}`
    }
    return text
  }).join('\n\n')
}
