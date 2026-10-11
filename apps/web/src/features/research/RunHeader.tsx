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
        {run.plugins && run.plugins.length > 0 && run.plugins.map((plugin) => (
          <span key={plugin} className="plugin-pill">
            {plugin === 'speed' && '⚡ Speed'}
            {plugin === 'accuracy' && '🛡️ Deep Verification'}
            {plugin === 'code' && '💻 Code Interpreter'}
            {!['speed', 'accuracy', 'code'].includes(plugin) && `🔌 ${plugin}`}
          </span>
        ))}
      </div>
    </div>
  )
}
