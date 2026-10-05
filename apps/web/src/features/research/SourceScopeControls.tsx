import { BookOpen, Code2, FileText, Globe2 } from 'lucide-react'
import type { SourceScope } from '../../lib/api/types'

const items: Array<{ id: SourceScope; label: string; icon: typeof Globe2 }> = [
  { id: 'web', label: 'Web', icon: Globe2 },
  { id: 'academic', label: 'Academic', icon: BookOpen },
  { id: 'software', label: 'Software', icon: Code2 },
  { id: 'documents', label: 'Documents', icon: FileText },
]

export function SourceScopeControls({
  value,
  onChange,
  selectedDocuments,
}: {
  value: SourceScope[]
  onChange: (value: SourceScope[]) => void
  selectedDocuments: number
}) {
  const toggle = (scope: SourceScope) => {
    const next = value.includes(scope) ? value.filter((item) => item !== scope) : [...value, scope]
    if (next.length > 0) onChange(next)
  }

  return (
    <div className="source-scope" aria-label="Research sources">
      {items.map(({ id, label, icon: Icon }) => {
        const selected = value.includes(id)
        return (
          <button
            key={id}
            type="button"
            className={selected ? 'selected' : ''}
            aria-pressed={selected}
            onClick={() => toggle(id)}
          >
            <Icon size={14} />
            <span>{label}</span>
            {id === 'documents' && selectedDocuments > 0 && <small>{selectedDocuments}</small>}
          </button>
        )
      })}
    </div>
  )
}
