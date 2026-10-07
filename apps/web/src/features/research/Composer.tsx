import { ArrowUp, Square } from 'lucide-react'
import { type FormEvent, type KeyboardEvent, useState } from 'react'
import type { RunMode, SourceScope, ModelProvider, ModelCatalog } from '../../lib/api/types'
import { SourceScopeControls } from './SourceScopeControls'

export function Composer({
  busy, readOnly = false, modelProvider, onModelProvider, models, mode, onMode, sourceScope, onSourceScope, selectedDocuments, onSubmit, onStop, placeholder
}: {
  modelProvider: ModelProvider
  onModelProvider: (provider: ModelProvider) => void
  models?: ModelCatalog
  busy: boolean
  readOnly?: boolean
  mode: RunMode
  onMode: (mode: RunMode) => void
  sourceScope: SourceScope[]
  onSourceScope: (value: SourceScope[]) => void
  selectedDocuments: number
  onSubmit: (query: string) => Promise<void>
  onStop: () => void
  placeholder?: string
}) {
  const [query, setQuery] = useState('')
  const submit = async () => {
    const value = query.trim()
    if (!value || busy || readOnly) return
    await onSubmit(value)
    setQuery('')
  }
  const onForm = (event: FormEvent) => { event.preventDefault(); void submit() }
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault(); void submit()
    }
  }
  return (
    <form className="composer" onSubmit={onForm}>
      <label htmlFor="research-query" className="sr-only">Ask ARES a research question</label>
      <textarea
        id="research-query"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={onKey}
        rows={2}
        placeholder={placeholder ?? "Ask a question worth tracing back to evidence…"}
        disabled={busy || readOnly}
      />
      <SourceScopeControls value={sourceScope} onChange={readOnly ? () => undefined : onSourceScope} selectedDocuments={selectedDocuments} />
      <div className="composer-actions">
        <div className="mode-toggle" aria-label="Research depth">
          <button type="button" disabled={readOnly} className={mode === 'quick' ? 'selected' : ''} onClick={() => onMode('quick')}>Quick</button>
          <button type="button" disabled={readOnly} className={mode === 'research' ? 'selected' : ''} onClick={() => onMode('research')}>Research</button>
        </div>
        <label className="model-selector">
          <span className="sr-only">Answer model</span>
          <select aria-label="Answer model" value={modelProvider} disabled={busy || readOnly || !models} onChange={(event) => onModelProvider(event.target.value as ModelProvider)}>
            {(models?.models ?? [{id: modelProvider, label: modelProvider === 'qwen' ? 'Qwen' : 'Gemini', model: '', available: true, location: modelProvider === 'qwen' ? 'local' : 'cloud'}]).map((item) => (
              <option key={item.id} value={item.id} disabled={!item.available}>{item.label}{item.location === 'local' ? ' · Local' : ' · Cloud'}{!item.available ? ' · Not configured' : ''}</option>
            ))}
          </select>
        </label>
        {busy ? (
          <button className="send-button stop" type="button" disabled={readOnly} onClick={onStop}><Square size={15} fill="currentColor" /> Stop</button>
        ) : (
          <button className="send-button" type="submit" disabled={readOnly || !query.trim()}><ArrowUp size={17} /> {readOnly ? 'Read only' : 'Ask'}</button>
        )}
      </div>
    </form>
  )
}
