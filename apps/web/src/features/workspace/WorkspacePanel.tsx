import { AlertTriangle, CheckCircle2, FileText, HardDrive, LoaderCircle, RotateCcw, ServerCog, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { AssetView, DocumentView, IngestionView, SystemStatus } from '../../lib/api/types'
import { buildLibraryFiles } from './libraryFiles'

function fileSize(bytes: number) { return bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB` }

export function WorkspacePanel({view, documents, assets, ingestions, system, selected, onClose, onSelect, onDelete, onCancelIngestion, onRetryIngestion, onDeleteAsset, uploading = false, uploadError, readOnly = false}: {
  view: 'documents' | 'system'
  documents: DocumentView[]
  assets: AssetView[]
  ingestions: IngestionView[]
  system?: SystemStatus
  selected: string[]
  onClose: () => void
  onSelect: (ids: string[]) => void
  onDelete: (id: string) => Promise<void>
  onCancelIngestion: (id: string) => Promise<void>
  onRetryIngestion: (id: string) => Promise<void>
  onDeleteAsset: (id: string) => Promise<void>
  readOnly?: boolean
  uploading?: boolean
  uploadError?: string
}) {
  const [error, setError] = useState<string>()
  const [pending, setPending] = useState<string>()
  const files = buildLibraryFiles(documents, assets, ingestions)
  const act = async (id: string, action: () => Promise<void>) => {
    setPending(id); setError(undefined)
    try { await action() } catch (error) { setError(error instanceof Error ? error.message : 'Could not update the file') }
    finally { setPending(undefined) }
  }
  return <aside className="workspace-panel" aria-label={view === 'documents' ? 'Uploaded files library' : 'System workspace'}>
    <div className="workspace-head"><div><h2>{view === 'documents' ? 'Library' : 'Settings'}</h2>{view === 'documents' && <span className="library-count">{files.length} uploaded file{files.length === 1 ? '' : 's'}</span>}</div><button className="icon-button" onClick={onClose} aria-label="Close workspace panel"><X size={18}/></button></div>
    {view === 'documents' ? <div className="workspace-content">
      {(error || uploadError) && <div className="panel-error" role="alert"><AlertTriangle size={16}/>{error || uploadError}</div>}
      {uploading && <div className="library-upload-status" role="status"><LoaderCircle className="spin" size={17}/>Uploading and reading your file…</div>}
      <div className="document-list">{files.map((file) => {
        const document = file.document
        const selectable = document && ['ready', 'partial'].includes(document.status) && (document.lexical_ready ?? true)
        const isSelected = Boolean(document && selected.includes(document.id))
        const status = document?.status ?? file.ingestion?.status ?? file.asset?.status ?? 'processing'
        const active = Boolean(file.ingestion && !['ready', 'partial', 'failed', 'cancelled'].includes(file.ingestion.status))
        return <article className={`document-card library-file-card ${isSelected ? 'selected' : ''}`} key={file.id}>
          <button className="document-select" disabled={!selectable || readOnly} aria-pressed={isSelected} onClick={() => { if (document) onSelect(isSelected ? selected.filter(id => id !== document.id) : [...selected, document.id]) }}>
            <span className="document-icon"><FileText size={18}/></span><span className="document-main"><strong>{file.name}</strong><small>{fileSize(file.bytes)} · {isSelected ? 'Selected' : status.replaceAll('_', ' ')}</small></span>{active && <LoaderCircle size={16} className="spin"/>}
          </button>
          <div className="library-file-actions">
            {active && file.ingestion && <button className="quiet-button" disabled={readOnly || Boolean(pending)} onClick={() => void act(file.id, () => onCancelIngestion(file.ingestion!.id))}>Cancel</button>}
            {file.ingestion && ['failed', 'cancelled'].includes(file.ingestion.status) && <button className="quiet-button" disabled={readOnly || Boolean(pending)} onClick={() => void act(file.id, () => onRetryIngestion(file.ingestion!.id))}><RotateCcw size={14}/>Retry</button>}
            <button className="icon-button danger-icon" aria-label={`Delete ${file.name}`} disabled={readOnly || Boolean(pending)} onClick={() => { if (window.confirm(`Delete “${file.name}” from your uploaded files?`)) void act(file.id, () => file.asset ? onDeleteAsset(file.asset.id) : onDelete(document!.id)) }}><Trash2 size={15}/></button>
          </div>
        </article>
      })}</div>
      {!files.length && !uploading && <div className="panel-empty"><HardDrive size={24}/><strong>No uploaded files yet</strong><span>Use the + beside Search to upload a file.</span></div>}
    </div> : (
        <div className="workspace-content">
          <p className="workspace-intro">Runtime capabilities are reported by the server. Secrets and raw credentials are never returned here.</p>
          <div className="system-card">
            <div><span>Deployment</span><strong>{system?.deployment_environment ?? 'unknown'}</strong></div>
            <div><span>Authentication</span><strong>{system?.auth_mode ?? 'unknown'}</strong></div>
            <div><span>Mode</span><strong>{system?.mode ?? 'unknown'}</strong></div>
            <div><span>Cost policy</span><strong>{system?.strict_free_mode ? 'Strict free' : 'Custom'}</strong></div>
            <div><span>Paid fallback</span><strong>{system?.billable_fallback_allowed ? 'Allowed' : 'Blocked'}</strong></div>
            <div><span>Retrieval</span><code>{system?.retrieval_backend ?? 'unknown'}</code></div>
            <div><span>Gemini</span><code>{system?.gemini_model ?? 'demo / disabled'}</code></div>
            <div><span>Workers</span><strong>{system ? `${system.worker_fleet.active} active · ${system.worker_fleet.draining} draining` : 'unknown'}</strong></div>
            <div><span>Audio evidence</span><strong>{system?.ingestion?.audio_ready ? 'Ready' : system?.tools.audio_transcription?.configured ? 'Configured · unavailable' : 'Off'}</strong></div>
            <div><span>Video evidence</span><strong>{system?.ingestion?.video_ready ? 'Ready' : system?.tools.video_sampling?.configured ? 'Configured · unavailable' : 'Off'}</strong></div>
            <div><span>Telemetry export</span><strong>{system?.telemetry_export.degraded ? 'Configured · unavailable' : system?.telemetry_export.ready ? 'Ready' : 'Local only'}</strong></div>
          </div>
          <h3 className="panel-section-title">Tool fabric</h3>
          <div className="tool-list">
            {Object.entries(system?.tools ?? {}).map(([name, tool]) => (
              <div className="tool-row" key={name}>
                <span className="tool-icon"><ServerCog size={15} /></span>
                <div><strong>{name.replaceAll('_', ' ')}</strong><small>{tool.metered ? 'metered' : 'free-first'}{tool.authenticated ? ' · authenticated' : ''}{tool.polite_pool ? ' · polite pool' : ''}</small></div>
                {tool.ready ?? tool.configured ? <CheckCircle2 className="tool-ok" size={17} aria-label="Ready" /> : tool.degraded ? <span className="tool-warn">Degraded</span> : <span className="tool-off">Off</span>}
              </div>
            ))}
          </div>
        </div>
    )}
  </aside>
}
