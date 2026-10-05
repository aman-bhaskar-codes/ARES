import { lazy, Suspense, useState, type ReactNode } from 'react'
import { CalendarDays, Download, GitCompareArrows, Network, Table2 } from 'lucide-react'
import { api } from '../../lib/api/client'
import type { VisualizationView } from '../../lib/api/types'
import { chartPoints, comparisonRows, evidenceGraph, timelineEvents } from './visualizationData'

const EvidenceChart = lazy(() => import('./EvidenceChart'))
const EvidenceGraph = lazy(() => import('./EvidenceGraph'))

function EvidenceButtons({ ids, onEvidence }: { ids: string[]; onEvidence: (id: string) => void }) {
  if (!ids.length) return <span className="visual-none">None</span>
  return <span className="visual-evidence-buttons">{ids.slice(0, 6).map((id, index) => <button key={id} onClick={() => onEvidence(id)} aria-label={`Open linked evidence ${index + 1}`}>{index + 1}</button>)}{ids.length > 6 && <small>+{ids.length - 6}</small>}</span>
}

function DownloadCsv({ view }: { view: VisualizationView }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  if (!view.approved_spec.allow_download_csv) return null

  const downloadCsv = async () => {
    setBusy(true)
    setError(undefined)
    try {
      const { blob, filename } = await api.downloadVisualizationCsv(view.run_id, view.id)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename || 'ares-visualization.csv'
      anchor.rel = 'noopener'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not export this visualization')
    } finally {
      setBusy(false)
    }
  }

  return <span className="visual-download-wrap">
    <button className="visual-download" disabled={busy} onClick={() => void downloadCsv()}><Download size={13}/>{busy ? 'Preparing…' : 'CSV + lineage'}</button>
    {error && <small className="visual-download-error" role="alert">{error}</small>}
  </span>
}

function Card({ view, children }: { view: VisualizationView; children: ReactNode }) {
  return <section className="visual-card" aria-labelledby={`visual-title-${view.id}`}>
    <div className="visual-card-head">
      <div><span className="eyebrow">Validated artifact</span><h3 id={`visual-title-${view.id}`}>{view.title}</h3><p>{view.description}</p></div>
      <div className="visual-card-actions"><span>{view.data_lineage.length} evidence link{view.data_lineage.length === 1 ? '' : 's'}</span><DownloadCsv view={view}/></div>
    </div>
    {children}
  </section>
}

function Comparison({ view, onEvidence }: { view: VisualizationView; onEvidence: (id: string) => void }) {
  const rows = comparisonRows(view)
  return <Card view={view}>{rows.length ? <div className="visual-table-scroll"><table className="visual-table"><thead><tr><th>Facet</th><th>Status</th><th>Supports</th><th>Conflicts</th><th>Independent origins</th><th>Evidence</th></tr></thead><tbody>{rows.map((row) => <tr key={row.facet}><th scope="row">{row.facet}</th><td><span className={`visual-status status-${row.status}`}>{row.status}</span><small>{row.rationale}</small></td><td>{row.supporting_count}</td><td>{row.conflicting_count}</td><td>{row.independent_origin_count}</td><td><EvidenceButtons ids={[...row.supporting_evidence_ids, ...row.conflicting_evidence_ids]} onEvidence={onEvidence}/></td></tr>)}</tbody></table></div> : <div className="visual-empty">No facet comparison passed validation.</div>}</Card>
}

function Numeric({ view, onEvidence }: { view: VisualizationView; onEvidence: (id: string) => void }) {
  const points = chartPoints(view)
  return <Card view={view}>
    <Suspense fallback={<div className="visual-loading">Loading chart renderer…</div>}><EvidenceChart visualization={view} onEvidence={onEvidence}/></Suspense>
    <details className="visual-data-table"><summary><Table2 size={14}/> Data table alternative</summary><div className="visual-table-scroll"><table className="visual-table"><thead><tr><th>Label</th><th>Value</th><th>Unit</th><th>Transform</th><th>Evidence</th></tr></thead><tbody>{points.map((point) => <tr key={point.id}><th scope="row">{point.label}</th><td>{point.value}</td><td>{point.unit ?? '—'}</td><td>{point.transform}<small>{point.transform_note}</small></td><td><EvidenceButtons ids={point.evidence_ids} onEvidence={onEvidence}/></td></tr>)}</tbody></table></div></details>
  </Card>
}

function Timeline({ view, onEvidence }: { view: VisualizationView; onEvidence: (id: string) => void }) {
  const events = timelineEvents(view)
  return <Card view={view}><ol className="evidence-timeline">{events.map((event) => <li key={event.id}><div className="timeline-date"><CalendarDays size={14}/><time dateTime={event.event_at}>{new Date(event.event_at).toLocaleDateString()}</time></div><div><strong>{event.label}</strong><p>{event.uncertainty}</p><EvidenceButtons ids={event.evidence_ids} onEvidence={onEvidence}/></div></li>)}</ol>{!events.length && <div className="visual-empty">No source publication dates were available. Retrieval time is not substituted.</div>}</Card>
}

function Graph({ view, onEvidence }: { view: VisualizationView; onEvidence: (id: string) => void }) {
  const graph = evidenceGraph(view)
  return <Card view={view}>
    <Suspense fallback={<div className="visual-loading">Loading bounded graph renderer…</div>}><EvidenceGraph visualization={view} onEvidence={onEvidence}/></Suspense>
    <details className="visual-data-table"><summary><Network size={14}/> Relationship table alternative</summary><div className="visual-table-scroll"><table className="visual-table"><thead><tr><th>From</th><th>Relation</th><th>To</th><th>Evidence</th></tr></thead><tbody>{graph.edges.map((edge) => <tr key={edge.id}><td>{graph.nodes.find((node) => node.id === edge.source)?.label ?? edge.source}</td><td>{edge.relation.replaceAll('_', ' ')}</td><td>{graph.nodes.find((node) => node.id === edge.target)?.label ?? edge.target}</td><td>{edge.evidence_id ? <EvidenceButtons ids={[edge.evidence_id]} onEvidence={onEvidence}/> : '—'}</td></tr>)}</tbody></table></div></details>
  </Card>
}

export function VisualizationWorkspace({ visualizations, loading, error, onEvidence }: { visualizations: VisualizationView[]; loading: boolean; error?: string; onEvidence: (id: string) => void }) {
  if (loading) return <div className="workspace-loading">Loading validated visual artifacts…</div>
  if (error) return <div className="workspace-empty"><strong>Visual artifacts are unavailable.</strong><span>{error}</span></div>
  if (!visualizations.length) return <div className="workspace-empty"><GitCompareArrows size={20}/><strong>No visualization-ready evidence yet.</strong><span>ARES only creates comparisons, charts, timelines, or maps when finalized data can be traced to stored evidence.</span></div>
  return <div className="visual-workspace">
    <div className="workspace-section-head"><div><span className="eyebrow">Comparisons & visual evidence</span><h2>Inspect derived research artifacts</h2></div><span className="workspace-count">{visualizations.length}</span></div>
    <div className="visual-integrity-note"><GitCompareArrows size={15}/><span>Every value shown here comes from the approved server representation. Selecting evidence opens its original locator; visual edges describe stored support relationships, not causation.</span></div>
    {visualizations.map((view) => view.kind === 'comparison_matrix' ? <Comparison key={view.id} view={view} onEvidence={onEvidence}/> : ['bar', 'line', 'scatter'].includes(view.kind) ? <Numeric key={view.id} view={view} onEvidence={onEvidence}/> : view.kind === 'timeline' ? <Timeline key={view.id} view={view} onEvidence={onEvidence}/> : view.kind === 'evidence_map' ? <Graph key={view.id} view={view} onEvidence={onEvidence}/> : null)}
  </div>
}
