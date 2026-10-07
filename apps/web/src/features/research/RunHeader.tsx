import type { RunSnapshot } from '../../lib/api/types'

interface RunHeaderProps {
  run: RunSnapshot
}

export function RunHeader({ run }: RunHeaderProps) {
  return (
    <div className="query-heading">
      <span>You asked</span>
      <h1>{run.query}</h1>
      <div className="run-meta">
        <span>{run.mode}</span>
        {run.model_provider && <span>{run.model_provider === "qwen" ? "Qwen · Local" : "Gemini · Cloud"}</span>}
        {run.source_scope.map((scope) => (
          <span key={scope}>{scope}</span>
        ))}
        {run.document_ids.length > 0 && (
          <span>
            {run.document_ids.length} document
            {run.document_ids.length === 1 ? '' : 's'}
          </span>
        )}
      </div>
    </div>
  )
}
