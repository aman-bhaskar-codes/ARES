import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function safeMarkdownUrl(url: string) {
  const value = url.trim()
  if (!value) return ''
  if ((value.startsWith('/') && !value.startsWith('//')) || value.startsWith('#')) return value
  try {
    const origin = typeof window !== 'undefined' ? window.location.origin : 'https://ares.invalid'
    const parsed = new URL(value, origin)
    return ['http:', 'https:', 'mailto:'].includes(parsed.protocol) ? value : ''
  } catch {
    return ''
  }
}

function SafeLink({ href, children }: { href?: string; children?: ReactNode }) {
  const safe = href ? safeMarkdownUrl(href) : ''
  if (!safe) return <span>{children}</span>
  const external = /^(?:https?:)?\/\//i.test(safe)
  return <a href={safe} target={external ? '_blank' : undefined} rel={external ? 'noreferrer' : undefined}>{children}</a>
}

export function SafeMarkdown({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={safeMarkdownUrl}
      components={{
        a: ({ href, children }) => <SafeLink href={href}>{children}</SafeLink>,
        table: ({ children }) => <div className="markdown-table-scroll"><table>{children}</table></div>,
        code: ({ className, children }) => <code className={className}>{children}</code>,
        pre: ({ children }) => <pre tabIndex={0}>{children}</pre>,
      }}
    >
      {markdown}
    </ReactMarkdown>
  )
}
