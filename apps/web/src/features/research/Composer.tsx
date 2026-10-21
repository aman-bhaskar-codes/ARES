import { ArrowUp, BookOpen, ChevronDown, Code2, Globe2, LoaderCircle, Plus, Search, ShieldCheck, SlidersHorizontal, Square, Zap } from 'lucide-react'
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from 'react'
import type { RunMode, SourceScope, ModelProvider, ModelCatalog } from '../../lib/api/types'
import { SourceScopeControls } from './SourceScopeControls'

const tools = [
  { id: 'speed', label: 'Fast retrieval', description: 'Use a smaller source and writing budget.', icon: Zap },
  { id: 'accuracy', label: 'Cross-check sources', description: 'Compare claims across retrieved sources.', icon: ShieldCheck },
  { id: 'code', label: 'Code interpreter', description: 'Use Python for calculations when available.', icon: Code2 },
]
const suggestions = [
  { icon: BookOpen, title: 'Understand a topic', question: 'Explain quantum superposition with a simple example and sources.' },
  { icon: Search, title: 'Compare ideas', question: 'Compare solar and wind energy: costs, reliability, and limitations.' },
  { icon: Code2, title: 'Explore technology', question: 'How does retrieval augmented generation work, and where does it fall short?' },
]

export function Composer({
  busy, readOnly = false, modelProvider, onModelProvider, models, mode, onMode, sourceScope, onSourceScope, selectedDocuments, plugins = [], onPlugins, onSubmit, onStop, placeholder, showSuggestions = false, onUpload, uploadAccept, uploading = false,
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
  plugins?: string[]
  onPlugins?: (plugins: string[]) => void
  onSubmit: (query: string) => Promise<void>
  onStop: () => void
  placeholder?: string
  showSuggestions?: boolean
  onUpload?: (files: File[]) => Promise<void>
  uploadAccept?: string
  uploading?: boolean
}) {
  const [query, setQuery] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const form = useRef<HTMLFormElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const locked = busy || readOnly || submitting || uploading
  useEffect(() => {
    const close = (event: PointerEvent | globalThis.KeyboardEvent) => {
      const escape = event instanceof globalThis.KeyboardEvent && event.key === 'Escape'
      if (!escape && form.current?.contains(event.target as Node)) return
      form.current?.querySelectorAll('details[open]').forEach((item) => {
        item.removeAttribute('open')
        if (escape) item.querySelector('summary')?.focus()
      })
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', close) }
  }, [])
  const submit = async () => {
    const value = query.trim()
    if (!value || locked) return
    form.current?.querySelectorAll('details[open]').forEach((item) => item.removeAttribute('open'))
    setSubmitting(true)
    try { await onSubmit(value); setQuery('') } catch { /* Workspace displays the error; keep the draft for retry. */ }
    finally { setSubmitting(false) }
  }
  const onForm = (event: FormEvent) => { event.preventDefault(); void submit() }
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault(); void submit()
    }
  }
  return <>
    <form className="composer" onSubmit={onForm} ref={form} aria-busy={submitting}>
      <label htmlFor="research-query" className="sr-only">Ask ARES a research question</label>
      <textarea ref={textarea} id="research-query" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={onKey}
        rows={2} placeholder={placeholder ?? 'Ask anything. Explore the sources.'} disabled={locked} />
      <input ref={fileInput} hidden type="file" multiple accept={uploadAccept} aria-label="Upload files" disabled={locked} onChange={(event) => { const files = Array.from(event.target.files ?? []); event.target.value = ''; if (files.length && onUpload) void onUpload(files) }} />
      <div className="composer-actions">
        {onUpload && <button className="attach-button" type="button" aria-label="Upload files" title="Upload files" disabled={locked} onClick={() => fileInput.current?.click()}>{uploading ? <LoaderCircle size={19} className="spin"/> : <Plus size={21}/>}</button>}
        <div className="mode-toggle" role="group" aria-label="Research depth">
          <button type="button" disabled={locked} aria-pressed={mode === 'quick'} className={mode === 'quick' ? 'selected' : ''} onClick={() => onMode('quick')}><Search size={15} /> Search</button>
          <button type="button" disabled={locked} aria-pressed={mode === 'research'} className={mode === 'research' ? 'selected' : ''} onClick={() => onMode('research')}><BookOpen size={15} /> Research</button>
        </div>
        <div className="composer-options">
        <details className="composer-disclosure" name="research-options">
          <summary><Globe2 size={16} /><span>Sources</span><ChevronDown size={13} /></summary>
          <div className="composer-popover"><strong>Where to search</strong><p>Choose one or more source types.</p><SourceScopeControls value={sourceScope} onChange={onSourceScope} selectedDocuments={selectedDocuments} disabled={locked} /></div>
        </details>
        {onPlugins && <details className="composer-disclosure tools-disclosure" name="research-options">
          <summary><SlidersHorizontal size={16} /><span>Tools</span>{plugins.length > 0 && <small>{plugins.length}</small>}</summary>
          <div className="composer-popover"><strong>Research tools</strong><p>Optional tools for this question.</p>{tools.map(({ id, label, description, icon: Icon }) => <button type="button" key={id} className="tool-option" disabled={locked} aria-pressed={plugins.includes(id)} onClick={() => onPlugins(plugins.includes(id) ? plugins.filter((value) => value !== id) : [...plugins, id])}>
            <Icon size={18} /><span><b>{label}</b><small>{description}</small></span><span className={`tool-switch ${plugins.includes(id) ? 'on' : ''}`} aria-hidden="true" />
          </button>)}</div>
        </details>}
        <label className="model-selector"><span className="sr-only">Answer model</span>
          <select aria-label="Answer model" value={modelProvider} disabled={locked || !models} onChange={(event) => onModelProvider(event.target.value as ModelProvider)}>
            {(models?.models ?? [{id: modelProvider, label: modelProvider === 'qwen' ? 'Qwen' : 'Gemini', model: '', available: true, location: modelProvider === 'qwen' ? 'local' : 'cloud'}]).map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.label}{item.location === 'local' ? ' · Local' : ''}{!item.available ? ' · Unavailable' : ''}</option>)}
          </select>
        </label>
        </div>
        {busy ? <button className="send-button stop" type="button" disabled={readOnly} onClick={onStop} aria-label="Stop research"><Square size={16} fill="currentColor" /></button>
          : <button className="send-button" type="submit" disabled={locked || !query.trim()} aria-label={readOnly ? 'Read only' : submitting ? 'Starting research' : 'Ask question'}>{submitting ? <LoaderCircle className="spin" size={19} /> : <ArrowUp size={20} />}</button>}
      </div>
      <div className="composer-context"><span>{sourceScope.map((scope) => scope === 'documents' ? `Documents (${selectedDocuments})` : scope.charAt(0).toUpperCase() + scope.slice(1)).join(' + ')}</span><span>Enter to ask · Shift + Enter for a new line</span></div>
    </form>
    {showSuggestions && <div className="starter-prompts" aria-label="Suggested questions">{suggestions.map(({ icon: Icon, title, question }) => <button key={title} type="button" disabled={locked} onClick={() => { setQuery(question); textarea.current?.focus() }}><Icon size={17} /><span>{title}</span></button>)}</div>}
  </>
}
