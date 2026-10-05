import {
  AlertTriangle,
  CheckCircle2,
  FileAudio,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileVideo,
  HardDrive,
  LoaderCircle,
  Mic,
  RotateCcw,
  Square,
  ServerCog,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { type ChangeEvent, type DragEvent, useEffect, useMemo, useRef, useState } from 'react'
import type { AssetView, DocumentView, IngestionView, SystemStatus } from '../../lib/api/types'

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 ** 2)).toFixed(1)} MB`
}

function DocumentStatus({ document }: { document: DocumentView }) {
  const label = document.status === 'needs_ocr' ? 'OCR needed' : document.status
  return <span className={`document-status status-${document.status}`}>{label.replace('_', ' ')}</span>
}

function AssetIcon({ mime }: { mime: string }) {
  if (mime === 'text/csv') return <FileSpreadsheet size={17} />
  if (mime.startsWith('image/')) return <FileImage size={17} />
  if (mime.startsWith('audio/')) return <FileAudio size={17} />
  if (mime.startsWith('video/')) return <FileVideo size={17} />
  return <FileText size={17} />
}

function formatDuration(durationMs?: number | null) {
  if (!durationMs) return undefined
  const totalSeconds = Math.round(durationMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

function uploadAccept(system?: SystemStatus, richIngestionReady = false) {
  const values = new Set(['text/plain', 'text/markdown', '.txt', '.md'])
  if (!richIngestionReady) {
    values.add('application/pdf'); values.add('.pdf')
    return Array.from(values).join(',')
  }
  const accepted = new Set(system?.ingestion?.accepted_mime_types ?? [])
  const extensionMap: Record<string, string[]> = {
    'application/pdf': ['.pdf'],
    'text/csv': ['.csv'],
    'image/png': ['.png'],
    'image/jpeg': ['.jpg', '.jpeg'],
    'image/webp': ['.webp'],
    'audio/wav': ['.wav'],
    'audio/mpeg': ['.mp3'],
    'audio/mp4': ['.m4a'],
    'audio/ogg': ['.ogg'],
    'audio/webm': ['.webm'],
    'video/mp4': ['.mp4'],
    'video/webm': ['.webm'],
  }
  for (const mime of accepted) {
    if (mime.startsWith('audio/') && !system?.ingestion?.audio_ready) continue
    if (mime.startsWith('video/') && !system?.ingestion?.video_ready) continue
    values.add(mime)
    for (const extension of extensionMap[mime] ?? []) values.add(extension)
  }
  return Array.from(values).join(',')
}

function mediaLabel(system?: SystemStatus) {
  const accepted = new Set(system?.ingestion?.accepted_mime_types ?? [])
  const labels = ['PDF', 'images', 'CSV', 'Markdown', 'text']
  if ([...accepted].some((item) => item.startsWith('audio/'))) labels.push('audio')
  if ([...accepted].some((item) => item.startsWith('video/'))) labels.push('short video')
  return labels.join(' · ')
}

function IngestionCard({
  ingestion,
  asset,
  readOnly,
  onCancel,
  onRetry,
  onDeleteAsset,
}: {
  ingestion: IngestionView
  asset?: AssetView
  readOnly: boolean
  onCancel: (id: string) => Promise<void>
  onRetry: (id: string) => Promise<void>
  onDeleteAsset: (id: string) => Promise<void>
}) {
  const terminal = ['ready', 'partial', 'failed', 'cancelled'].includes(ingestion.status)
  const retryable = ['failed', 'cancelled'].includes(ingestion.status)
  return (
    <article className={`ingestion-card ingestion-${ingestion.status}`}>
      <div className="ingestion-card-head">
        <span className="document-icon"><AssetIcon mime={asset?.mime_type ?? 'application/octet-stream'} /></span>
        <span className="document-main">
          <strong>{asset?.name ?? 'Uploaded asset'}</strong>
          <small>{asset ? formatBytes(asset.byte_count) : 'Preparing asset'}{formatDuration(asset?.duration_ms) ? ` · ${formatDuration(asset?.duration_ms)}` : ''} · {ingestion.stage.replaceAll('_', ' ')}</small>
        </span>
        {!terminal && <LoaderCircle className="spin" size={16} aria-label="Processing" />}
      </div>
      <div className="readiness-row" aria-label="Ingestion readiness">
        <span className={ingestion.lexical_ready ? 'ready' : ''}>{ingestion.lexical_ready ? <CheckCircle2 size={13}/> : <span className="readiness-dot" />} Searchable text</span>
        <span className={ingestion.semantic_ready ? 'ready' : ''}>{ingestion.semantic_ready ? <CheckCircle2 size={13}/> : <span className="readiness-dot" />} Semantic index</span>
      </div>
      {ingestion.error_message && <p className="document-warning"><AlertTriangle size={13}/>{ingestion.error_message}</p>}
      {ingestion.warnings.map((warning) => <p className="document-warning" key={warning}><AlertTriangle size={13}/>{warning}</p>)}
      <div className="ingestion-actions">
        {!terminal && (
          <button className="quiet-panel-button" disabled={readOnly || ingestion.cancellation_requested} onClick={() => void onCancel(ingestion.id)}>
            <X size={14}/>{ingestion.cancellation_requested ? 'Stopping…' : 'Cancel'}
          </button>
        )}
        {retryable && (
          <button className="quiet-panel-button" disabled={readOnly} onClick={() => void onRetry(ingestion.id)}>
            <RotateCcw size={14}/>Retry
          </button>
        )}
        {terminal && asset && !ingestion.document_id && (
          <button
            className="quiet-panel-button danger"
            disabled={readOnly}
            onClick={() => {
              if (window.confirm(`Delete “${asset.name}” and all of its derived media data?`)) {
                void onDeleteAsset(asset.id)
              }
            }}
          >
            <Trash2 size={14}/>Delete upload
          </button>
        )}
      </div>
    </article>
  )
}

export function WorkspacePanel({
  view,
  documents,
  assets,
  ingestions,
  system,
  selected,
  busyUpload,
  richIngestionReady,
  onClose,
  onSelect,
  onUpload,
  onDelete,
  onCancelIngestion,
  onRetryIngestion,
  onDeleteAsset,
  readOnly = false,
}: {
  view: 'documents' | 'system'
  documents: DocumentView[]
  assets: AssetView[]
  ingestions: IngestionView[]
  system?: SystemStatus
  selected: string[]
  busyUpload: boolean
  richIngestionReady: boolean
  onClose: () => void
  onSelect: (ids: string[]) => void
  onUpload: (file: File) => Promise<void>
  onDelete: (documentId: string) => Promise<void>
  onCancelIngestion: (ingestionId: string) => Promise<void>
  onRetryIngestion: (ingestionId: string) => Promise<void>
  onDeleteAsset: (assetId: string) => Promise<void>
  readOnly?: boolean
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const recordingStreamRef = useRef<MediaStream | null>(null)
  const recordingChunksRef = useRef<Blob[]>([])
  const recordingTimerRef = useRef<number | undefined>(undefined)
  const [recording, setRecording] = useState(false)
  const [localError, setLocalError] = useState<string>()
  const [dragging, setDragging] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DocumentView>()
  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets])
  const visibleIngestions = ingestions.slice(0, 12)
  const microphoneReady = Boolean(system?.ingestion?.microphone_enabled && system?.ingestion?.audio_ready)

  const stopRecording = () => {
    if (recordingTimerRef.current !== undefined) window.clearTimeout(recordingTimerRef.current)
    recordingTimerRef.current = undefined
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
  }

  useEffect(() => () => {
    if (recordingTimerRef.current !== undefined) window.clearTimeout(recordingTimerRef.current)
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
    recordingStreamRef.current?.getTracks().forEach((track) => track.stop())
  }, [])

  const startRecording = async () => {
    setLocalError(undefined)
    if (!microphoneReady) { setLocalError('Microphone recording is not ready on the current media worker.'); return }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setLocalError('Microphone capture requires a supported browser in a secure HTTPS or localhost context.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      const candidates = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm', 'audio/ogg;codecs=opus']
      const mimeType = candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate))
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recordingStreamRef.current = stream
      recorderRef.current = recorder
      recordingChunksRef.current = []
      recorder.ondataavailable = (event) => { if (event.data.size > 0) recordingChunksRef.current.push(event.data) }
      recorder.onerror = () => setLocalError('The browser could not continue microphone recording.')
      recorder.onstop = () => {
        const chosen = recorder.mimeType || mimeType || 'audio/webm'
        const baseMime = chosen.split(';', 1)[0]
        const extension = baseMime === 'audio/mp4' ? 'm4a' : baseMime === 'audio/ogg' ? 'ogg' : 'webm'
        const blob = new Blob(recordingChunksRef.current, { type: chosen })
        recordingChunksRef.current = []
        recordingStreamRef.current?.getTracks().forEach((track) => track.stop())
        recordingStreamRef.current = null
        recorderRef.current = null
        setRecording(false)
        if (blob.size > 0) {
          const file = new File([blob], `microphone-${new Date().toISOString().replaceAll(':', '-')}.${extension}`, { type: chosen })
          void onUpload(file).catch((error) => setLocalError(error instanceof Error ? error.message : 'Microphone upload failed.'))
        }
      }
      recorder.start(1000)
      setRecording(true)
      const maxSeconds = system?.ingestion?.max_audio_duration_seconds ?? 600
      recordingTimerRef.current = window.setTimeout(stopRecording, maxSeconds * 1000)
    } catch (error) {
      recordingStreamRef.current?.getTracks().forEach((track) => track.stop())
      recordingStreamRef.current = null
      setRecording(false)
      setLocalError(error instanceof Error ? error.message : 'Microphone permission was not granted.')
    }
  }

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return
    setLocalError(undefined)
    try {
      for (const file of files) await onUpload(file)
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Upload failed')
    }
  }

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    await uploadFiles(files)
  }

  const drop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    if (readOnly || busyUpload) return
    await uploadFiles(Array.from(event.dataTransfer.files ?? []))
  }

  const toggle = (document: DocumentView) => {
    if (readOnly || !['ready', 'partial'].includes(document.status) || !(document.lexical_ready ?? true)) return
    onSelect(selected.includes(document.id) ? selected.filter((id) => id !== document.id) : [...selected, document.id])
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    try {
      await onDelete(deleteTarget.id)
      setDeleteTarget(undefined)
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Delete failed')
      setDeleteTarget(undefined)
    }
  }

  return (
    <aside className="workspace-panel" aria-label={view === 'documents' ? 'Documents workspace' : 'System workspace'}>
      <div className="workspace-head">
        <div>
          <div className="eyebrow">Workspace</div>
          <h2>{view === 'documents' ? 'Documents & evidence' : 'System'}</h2>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="Close workspace panel"><X size={18} /></button>
      </div>

      {view === 'documents' ? (
        <div className="workspace-content">
          <p className="workspace-intro">Upload source material once, let ARES extract it in the background, then use searchable documents in research runs.</p>
          <input
            ref={fileRef}
            className="sr-only"
            type="file"
            multiple
            accept={uploadAccept(system, richIngestionReady)}
            onChange={(event) => void upload(event)}
            disabled={readOnly}
          />
          <div
            className={`upload-dropzone ${dragging ? 'dragging' : ''}`}
            onDragEnter={(event) => { event.preventDefault(); if (!readOnly) setDragging(true) }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false) }}
            onDrop={(event) => void drop(event)}
          >
            <Upload size={20}/>
            <div><strong>Drop research files here</strong><span>{richIngestionReady ? mediaLabel(system) : 'PDF · Markdown · text'}</span></div>
            <button className="primary-panel-action" disabled={busyUpload || readOnly} onClick={() => fileRef.current?.click()}>
              {busyUpload ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}
              {readOnly ? 'Read-only workspace' : busyUpload ? 'Uploading…' : 'Choose files'}
            </button>
          </div>
          {microphoneReady && (
            <div className="microphone-row">
              <button
                className={recording ? 'danger-panel-button' : 'quiet-panel-button'}
                disabled={busyUpload || readOnly}
                onClick={() => recording ? stopRecording() : void startRecording()}
                aria-pressed={recording}
              >
                {recording ? <Square size={14}/> : <Mic size={15}/>}
                {recording ? 'Stop recording' : 'Record a question'}
              </button>
              <span role="status">{recording ? 'Recording locally; stop to upload for transcription.' : 'Browser permission is requested only when you start.'}</span>
            </div>
          )}
          {!richIngestionReady && <div className="panel-note"><AlertTriangle size={14}/>Rich ingestion is unavailable on the current worker profile. Existing PDF/text upload remains available.</div>}
          {system?.ingestion?.enabled && system.ingestion.accepted_mime_types.some((mime) => mime.startsWith('audio/')) && !system.ingestion.audio_ready && <div className="panel-note"><AlertTriangle size={14}/>Audio is configured but the ASR/FFmpeg worker capability is not ready. Audio uploads are disabled until that worker is healthy.</div>}
          {system?.ingestion?.enabled && system.ingestion.accepted_mime_types.some((mime) => mime.startsWith('video/')) && !system.ingestion.video_ready && <div className="panel-note"><AlertTriangle size={14}/>Video is configured but the media worker capability is not ready. Video uploads are disabled until that worker is healthy.</div>}
          {localError && <div className="panel-error" role="alert"><AlertTriangle size={15} />{localError}</div>}

          {visibleIngestions.length > 0 && <>
            <h3 className="panel-section-title">Processing</h3>
            <div className="ingestion-list">
              {visibleIngestions.map((ingestion) => (
                <IngestionCard
                  key={ingestion.id}
                  ingestion={ingestion}
                  asset={assetById.get(ingestion.asset_id)}
                  readOnly={readOnly}
                  onCancel={onCancelIngestion}
                  onRetry={onRetryIngestion}
              onDeleteAsset={onDeleteAsset}
                />
              ))}
            </div>
          </>}

          <h3 className="panel-section-title">Research documents</h3>
          <div className="document-list">
            {documents.map((document) => {
              const selectable = ['ready', 'partial'].includes(document.status) && (document.lexical_ready ?? true)
              const isSelected = selected.includes(document.id)
              return (
                <article key={document.id} className={`document-card ${isSelected ? 'selected' : ''}`}>
                  <button className="document-select" disabled={!selectable || readOnly} onClick={() => toggle(document)} aria-pressed={isSelected}>
                    <span className="document-icon"><AssetIcon mime={document.mime_type} /></span>
                    <span className="document-main">
                      <strong>{document.name}</strong>
                      <small>{formatBytes(document.byte_count)}{document.page_count ? ` · ${document.page_count} pages` : ''}</small>
                    </span>
                    <DocumentStatus document={document} />
                  </button>
                  <div className="readiness-row compact">
                    <span className={(document.lexical_ready ?? true) ? 'ready' : ''}>{(document.lexical_ready ?? true) ? <CheckCircle2 size={12}/> : <span className="readiness-dot"/>} Lexical</span>
                    <span className={document.semantic_ready ? 'ready' : ''}>{document.semantic_ready ? <CheckCircle2 size={12}/> : <span className="readiness-dot"/>} Semantic</span>
                  </div>
                  {document.warnings.map((warning) => <p className="document-warning" key={warning}><AlertTriangle size={13} />{warning}</p>)}
                  <div className="document-footer">
                    <code>{document.content_hash.slice(0, 12)}…</code>
                    <button className="icon-button danger-icon" disabled={readOnly} onClick={() => setDeleteTarget(document)} aria-label={`Delete ${document.name}`}><Trash2 size={15} /></button>
                  </div>
                </article>
              )
            })}
            {documents.length === 0 && <div className="panel-empty"><HardDrive size={20} /><strong>No documents yet</strong><span>Upload a paper, scan, image, table, or notes to create local evidence.</span></div>}
          </div>
        </div>
      ) : (
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

      {deleteTarget && (
        <div className="dialog-scrim" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) setDeleteTarget(undefined) }}>
          <div className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-document-title" aria-describedby="delete-document-description">
            <div className="eyebrow">Delete source</div>
            <h3 id="delete-document-title">Delete “{deleteTarget.name}”?</h3>
            <p id="delete-document-description">This removes the document from future research retrieval. Existing finalized runs retain their recorded provenance according to the repository retention policy.</p>
            <div className="dialog-actions">
              <button autoFocus className="quiet-panel-button" onClick={() => setDeleteTarget(undefined)}>Keep document</button>
              <button className="danger-panel-button" onClick={() => void confirmDelete()}><Trash2 size={14}/>Delete</button>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
