import { useQuery } from '@tanstack/react-query'
import { ExternalLink, FileAudio, FileImage, FileText, FileVideo, Grid3X3, Play, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api } from '../../lib/api/client'
import type {
  Evidence,
  FrameRegionEvidenceLocator,
  MediaStoryboardView,
  PageRegionEvidenceLocator,
  TableCellsEvidenceLocator,
  TableView,
} from '../../lib/api/types'


function formatTimestamp(milliseconds: number) {
  const totalSeconds = Math.max(0, milliseconds) / 1000
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds - minutes * 60
  return `${minutes}:${seconds.toFixed(seconds < 10 ? 1 : 0).padStart(seconds < 10 ? 4 : 2, '0')}`
}

function MediaEvidencePreview({
  url, mime, startMs, endMs, name, waveformPeaks,
}: {
  url: string
  mime?: string | null
  startMs: number
  endMs?: number
  name?: string | null
  waveformPeaks?: number[]
}) {
  const mediaRef = useRef<HTMLMediaElement>(null)
  const isVideo = Boolean(mime?.startsWith('video/'))
  const seek = () => {
    const media = mediaRef.current
    if (!media) return
    media.currentTime = Math.max(0, startMs / 1000)
  }
  useEffect(() => {
    const media = mediaRef.current
    if (media) media.currentTime = Math.max(0, startMs / 1000)
  }, [startMs, url])
  return (
    <section className="evidence-preview media-evidence-preview" aria-label="Cited media interval">
      <div className="evidence-preview-head">
        {isVideo ? <FileVideo size={14}/> : <FileAudio size={14}/>}
        <strong>Original {isVideo ? 'video' : 'audio'}</strong>
        <span>{formatTimestamp(startMs)}{endMs ? `–${formatTimestamp(endMs)}` : ''}</span>
      </div>
      {waveformPeaks && waveformPeaks.length > 0 && (
        <div className="media-waveform" aria-hidden="true">
          {waveformPeaks.map((peak, index) => (
            <span key={index} style={{ height: `${Math.max(8, Math.round(peak * 100))}%` }} />
          ))}
        </div>
      )}
      {isVideo ? (
        <video ref={(node) => { mediaRef.current = node }} src={url} controls preload="metadata" onLoadedMetadata={seek} aria-label={name ?? 'Uploaded video source'} />
      ) : (
        <audio ref={(node) => { mediaRef.current = node }} src={url} controls preload="metadata" onLoadedMetadata={seek} aria-label={name ?? 'Uploaded audio source'} />
      )}
      <button className="quiet-panel-button media-seek-button" onClick={seek}><Play size={13}/>Seek to cited evidence</button>
    </section>
  )
}

function FrameEvidencePreview({
  url, mime, locator, storyboard, name,
}: {
  url: string
  mime?: string | null
  locator: FrameRegionEvidenceLocator
  storyboard?: MediaStoryboardView
  name?: string | null
}) {
  const closest = storyboard?.frames.reduce((best, frame) =>
    !best || Math.abs(frame.presentation_time_ms - locator.presentation_time_ms) < Math.abs(best.presentation_time_ms - locator.presentation_time_ms) ? frame : best,
    undefined as MediaStoryboardView['frames'][number] | undefined,
  )
  const [left, top, right, bottom] = locator.bbox
  return (
    <>
      {closest && (
        <section className="evidence-preview" aria-label="Sampled frame nearest the cited visual region">
          <div className="evidence-preview-head"><FileImage size={14}/><strong>Sampled frame</strong><span>{formatTimestamp(closest.presentation_time_ms)}</span></div>
          <div className="image-evidence-stage">
            <img src={closest.content_url} alt={`Sampled frame at ${formatTimestamp(closest.presentation_time_ms)}`} />
            <span className="evidence-region-overlay" aria-hidden="true" style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${(right - left) * 100}%`, height: `${(bottom - top) * 100}%` }} />
          </div>
          {storyboard?.visual_coverage_warning && <p className="preview-caption">{storyboard.visual_coverage_warning}</p>}
        </section>
      )}
      <MediaEvidencePreview url={url} mime={mime} startMs={locator.presentation_time_ms} name={name} waveformPeaks={storyboard?.waveform_peaks}/>
    </>
  )
}

function pages(evidence: Evidence) {
  if (evidence.page_start === null) return null
  if (evidence.page_end === null || evidence.page_end === evidence.page_start) return `Page ${evidence.page_start}`
  return `Pages ${evidence.page_start}–${evidence.page_end}`
}

function PageRegionOverlay({ locator }: { locator: PageRegionEvidenceLocator }) {
  const [left, top, right, bottom] = locator.bbox
  return (
    <span
      className="evidence-region-overlay"
      aria-hidden="true"
      style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${(right - left) * 100}%`, height: `${(bottom - top) * 100}%` }}
    />
  )
}

function PdfEvidencePreview({ url, locator }: { url: string; locator: PageRegionEvidenceLocator }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [error, setError] = useState<string>()
  const [rendering, setRendering] = useState(true)

  useEffect(() => {
    let cancelled = false
    let loadingTask: { destroy: () => Promise<void> } | undefined
    let renderTask: { cancel: () => void } | undefined

    const render = async () => {
      setRendering(true)
      setError(undefined)
      try {
        const pdfjs = await import('pdfjs-dist')
        pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
        const task = pdfjs.getDocument({ url })
        loadingTask = task
        const pdf = await task.promise
        const page = await pdf.getPage(locator.page)
        if (cancelled || !canvasRef.current) return
        const base = page.getViewport({ scale: 1 })
        const scale = Math.min(1.5, 650 / Math.max(1, base.width))
        const viewport = page.getViewport({ scale })
        const canvas = canvasRef.current
        const context = canvas.getContext('2d')
        if (!context) throw new Error('Canvas is unavailable in this browser')
        const ratio = Math.min(2, window.devicePixelRatio || 1)
        canvas.width = Math.floor(viewport.width * ratio)
        canvas.height = Math.floor(viewport.height * ratio)
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`
        const current = page.render({
          canvas,
          canvasContext: context,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        })
        renderTask = current
        await current.promise
        if (!cancelled) setRendering(false)
      } catch (caught) {
        if (!cancelled) {
          setRendering(false)
          setError(caught instanceof Error ? caught.message : 'Could not render the cited PDF page')
        }
      }
    }
    void render()
    return () => {
      cancelled = true
      renderTask?.cancel()
      void loadingTask?.destroy()
    }
  }, [locator.page, url])

  return (
    <section className="evidence-preview" aria-label={`Cited region on page ${locator.page}`}>
      <div className="evidence-preview-head"><FileText size={14}/><strong>Original page</strong><span>Page {locator.page}</span></div>
      {rendering && <div className="preview-loading">Rendering cited page…</div>}
      {error ? <div className="preview-error"><span>{error}</span><a href={url} target="_blank" rel="noreferrer">Open original PDF</a></div> : (
        <div className={`pdf-page-stage ${rendering ? 'is-loading' : ''}`}>
          <canvas ref={canvasRef}/>
          {!rendering && <PageRegionOverlay locator={locator}/>} 
        </div>
      )}
    </section>
  )
}

function ImageEvidencePreview({ url, locator, name }: { url: string; locator: PageRegionEvidenceLocator; name?: string | null }) {
  return (
    <section className="evidence-preview" aria-label="Cited image region">
      <div className="evidence-preview-head"><FileImage size={14}/><strong>Original image</strong><span>{name ?? 'Uploaded image'}</span></div>
      <div className="image-evidence-stage">
        <img src={url} alt={name ? `Uploaded source: ${name}` : 'Uploaded source'} />
        <PageRegionOverlay locator={locator}/>
      </div>
    </section>
  )
}

function boundedWindow(locator: TableCellsEvidenceLocator, table: TableView) {
  const selectedRows = locator.rows.length ? locator.rows : [0]
  const selectedColumns = locator.columns.length ? locator.columns : [0]
  const rowStart = Math.max(0, Math.min(...selectedRows) - 4)
  const rowEnd = Math.min(table.rows - 1, Math.max(...selectedRows) + 4)
  const columnStart = Math.max(0, Math.min(...selectedColumns) - 3)
  const columnEnd = Math.min(table.columns - 1, Math.max(...selectedColumns) + 3)
  return { rowStart, rowEnd, columnStart, columnEnd }
}

function TableEvidencePreview({ table, locator }: { table: TableView; locator: TableCellsEvidenceLocator }) {
  const window = useMemo(() => boundedWindow(locator, table), [locator, table])
  const rows = Array.from({ length: Math.max(0, window.rowEnd - window.rowStart + 1) }, (_, index) => window.rowStart + index)
  const columns = Array.from({ length: Math.max(0, window.columnEnd - window.columnStart + 1) }, (_, index) => window.columnStart + index)
  const cells = useMemo(() => new Map(table.cells.map((cell) => [`${cell.row}:${cell.column}`, cell])), [table.cells])
  const selectedRows = new Set(locator.rows)
  const selectedColumns = new Set(locator.columns)
  const clipped = rows.length < table.rows || columns.length < table.columns

  return (
    <section className="evidence-preview" aria-label="Cited table cells">
      <div className="evidence-preview-head"><Grid3X3 size={14}/><strong>Source table</strong><span>{table.rows} × {table.columns}</span></div>
      <div className="table-preview-scroll">
        <table className="evidence-table">
          <tbody>
            {rows.map((row) => (
              <tr key={row}>
                {columns.map((column) => {
                  const cell = cells.get(`${row}:${column}`)
                  const highlighted = selectedRows.has(row) && selectedColumns.has(column)
                  const Tag = cell?.is_header ? 'th' : 'td'
                  return <Tag key={column} className={highlighted ? 'cited-cell' : ''}>{cell?.raw_text ?? ''}</Tag>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {clipped && <p className="preview-caption">Showing a bounded window around the cited cells. The stored table has {table.rows} rows and {table.columns} columns.</p>}
    </section>
  )
}

function EvidenceAssetPreview({ evidence }: { evidence: Evidence }) {
  const locator = evidence.locator_data
  const table = useQuery({
    queryKey: ['evidence-table', evidence.segment_id],
    queryFn: () => api.getSegmentTable(evidence.segment_id!),
    enabled: Boolean(locator?.kind === 'table_cells' && evidence.segment_id),
    staleTime: Infinity,
    retry: false,
  })
  const storyboard = useQuery({
    queryKey: ['media-storyboard', evidence.asset_id],
    queryFn: () => api.getMediaStoryboard(evidence.asset_id!),
    enabled: Boolean(evidence.asset_id && (locator?.kind === 'time_range' || locator?.kind === 'frame_region')),
    staleTime: Infinity,
    retry: false,
  })
  if (!locator || !evidence.asset_content_url) return null
  if (locator.kind === 'table_cells') {
    if (table.isLoading) return <div className="preview-loading">Loading cited table cells…</div>
    if (table.isError || !table.data) return <div className="preview-error">The structured table preview is unavailable; the quoted evidence remains preserved below.</div>
    return <TableEvidencePreview table={table.data} locator={locator}/>
  }
  if (locator.kind === 'time_range') {
    return <MediaEvidencePreview url={evidence.asset_content_url} mime={evidence.asset_mime_type} startMs={locator.start_ms} endMs={locator.end_ms} name={evidence.asset_name} waveformPeaks={storyboard.data?.waveform_peaks}/>
  }
  if (locator.kind === 'frame_region') {
    return <FrameEvidencePreview url={evidence.asset_content_url} mime={evidence.asset_mime_type} locator={locator} storyboard={storyboard.data} name={evidence.asset_name}/>
  }
  if (locator.kind !== 'page_region') return null
  if (evidence.asset_mime_type === 'application/pdf') return <PdfEvidencePreview url={evidence.asset_content_url} locator={locator}/>
  if (evidence.asset_mime_type?.startsWith('image/')) return <ImageEvidencePreview url={evidence.asset_content_url} locator={locator} name={evidence.asset_name}/>
  return null
}

export function EvidenceDrawer({ evidence, onClose }: { evidence: Evidence; onClose: () => void }) {
  const drawerRef = useRef<HTMLElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)
  const locator = evidence.locator_data

  useEffect(() => { onCloseRef.current = onClose }, [onClose])
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !drawerRef.current) return
      const focusable = [...drawerRef.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
        .filter((element) => !element.hasAttribute('hidden'))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      if (previousFocus && document.contains(previousFocus)) previousFocus.focus()
    }
  }, [evidence.id])
  const locatorLabel = locator?.kind === 'page_region'
    ? `Page ${locator.page} · cited region`
    : locator?.kind === 'table_cells'
      ? `Table cells · row ${locator.rows.map((row) => row + 1).join(', ')} · column ${locator.columns.map((column) => column + 1).join(', ')}`
      : locator?.kind === 'time_range'
        ? `${locator.track === 'video' ? 'Video transcript' : 'Audio'} · ${formatTimestamp(locator.start_ms)}–${formatTimestamp(locator.end_ms)}`
        : locator?.kind === 'frame_region'
          ? `Video frame · ${formatTimestamp(locator.presentation_time_ms)}`
          : pages(evidence) ?? evidence.locator

  return (
    <aside ref={drawerRef} className="evidence-drawer" role="dialog" aria-modal="true" aria-label="Citation evidence">
      <div className="drawer-head">
        <div>
          <div className="eyebrow">{evidence.source.source_kind} evidence</div>
          <h2>{evidence.source.title}</h2>
        </div>
        <button ref={closeRef} className="icon-button" onClick={onClose} aria-label="Close evidence"><X size={18} /></button>
      </div>
      <div className="source-meta" style={{ marginBottom: '24px' }}>
        <span>{evidence.source.domain}</span>
        {evidence.source.published_at && <><span>·</span><span>{new Date(evidence.source.published_at).toLocaleDateString()}</span></>}
        <span>·</span><span>{locatorLabel}</span>
      </div>

      <div className="drawer-cited-evidence" style={{ marginBottom: '24px' }}>
        <blockquote style={{ marginTop: 0, marginBottom: '16px', fontSize: '15px', color: 'var(--ink)', borderLeft: '3px solid var(--accent)' }}>{evidence.text}</blockquote>
        <EvidenceAssetPreview evidence={evidence}/>
      </div>

      <div className="drawer-support-context" style={{ marginBottom: '24px', padding: '16px', background: 'var(--surface-sunken)', borderRadius: '8px' }}>
        <div style={{ fontSize: '12px', color: 'var(--ink-light)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Support context</div>
        <div style={{ fontWeight: 600, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="support-dot" data-support={evidence.support_status} style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'currentColor' }} />
          {evidence.support_status.replaceAll('_', ' ').toUpperCase()}
        </div>
      </div>

      <div className="drawer-actions" style={{ marginBottom: '32px' }}>
        {evidence.asset_content_url ? (
          <a className="button" href={evidence.asset_content_url} target="_blank" rel="noreferrer" style={{ width: '100%', justifyContent: 'center' }}>
            Open original asset <ExternalLink size={15} />
          </a>
        ) : (evidence.source.url && evidence.source.domain !== 'local.ares.invalid') ? (
          <a className="button" href={evidence.source.url} target="_blank" rel="noreferrer" style={{ width: '100%', justifyContent: 'center' }}>
            Open original source <ExternalLink size={15} />
          </a>
        ) : null}
      </div>

      <details className="evidence-facts-details">
        <summary style={{ cursor: 'pointer', fontSize: '13px', color: 'var(--ink-light)', padding: '12px 0', borderTop: '1px solid var(--line)', fontWeight: 500 }}>Technical provenance</summary>
        <div className="evidence-facts" style={{ marginTop: '12px' }}>
          {evidence.source.canonical_identifier && <div><span>Identifier</span><code>{evidence.source.canonical_identifier}</code></div>}
          <div><span>Captured</span><strong>{new Date(evidence.captured_at).toLocaleString()}</strong></div>
          <div><span>Method</span><strong>{evidence.source.extraction_method}</strong></div>
          <div><span>Provider</span><strong>{evidence.source.provider}</strong></div>
          <div><span>Version hash</span><code>{evidence.content_hash.slice(0, 16)}…</code></div>
          {evidence.asset_name && <div><span>Asset</span><strong>{evidence.asset_name}</strong></div>}
          {evidence.document_version_id && <div><span>Document version</span><code>{evidence.document_version_id.slice(0, 8)}…</code></div>}
          {evidence.char_start !== null && evidence.char_end !== null && (
            <div><span>Source offsets</span><code>{evidence.char_start}–{evidence.char_end}</code></div>
          )}
        </div>
      </details>
    </aside>
  )
}
