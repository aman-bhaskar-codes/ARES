import type { KeyboardEvent, MouseEvent } from 'react'

interface CitationChipProps {
  label: number
  evidenceId: string
  sourceTitle?: string
  sourceDomain?: string
  onOpen: (evidenceId: string, trigger?: HTMLElement) => void
}

export function CitationChip({ label, evidenceId, sourceTitle, sourceDomain, onOpen }: CitationChipProps) {
  const ariaLabel = `Open evidence source ${label}${sourceTitle ? `: ${sourceTitle}` : ''}${sourceDomain ? ` from ${sourceDomain}` : ''}`

  const handleClick = (e: MouseEvent<HTMLButtonElement>) => {
    onOpen(evidenceId, e.currentTarget)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onOpen(evidenceId, e.currentTarget)
    }
  }

  return (
    <button
      className="citation-button"
      aria-label={ariaLabel}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      {label}
    </button>
  )
}
