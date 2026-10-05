import type {
  ChartPoint,
  ComparisonMatrixRow,
  EvidenceGraphEdge,
  EvidenceGraphNode,
  TimelineEvent,
  VisualizationView,
} from '../../lib/api/types'

type UnknownRecord = Record<string, unknown>

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stringArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) return null
  return value
}

export function comparisonRows(view: VisualizationView): ComparisonMatrixRow[] {
  if (view.kind !== 'comparison_matrix') return []
  const rows = isRecord(view.dataset) ? view.dataset.rows : undefined
  if (!Array.isArray(rows)) return []
  return rows.flatMap((raw) => {
    if (!isRecord(raw)) return []
    const supporting = stringArray(raw.supporting_evidence_ids)
    const conflicting = stringArray(raw.conflicting_evidence_ids)
    if (
      typeof raw.facet !== 'string' ||
      !['supported', 'conflicting', 'missing'].includes(String(raw.status)) ||
      typeof raw.supporting_count !== 'number' || !Number.isInteger(raw.supporting_count) || raw.supporting_count < 0 ||
      typeof raw.conflicting_count !== 'number' || !Number.isInteger(raw.conflicting_count) || raw.conflicting_count < 0 ||
      typeof raw.independent_origin_count !== 'number' || !Number.isInteger(raw.independent_origin_count) || raw.independent_origin_count < 0 ||
      supporting === null || conflicting === null || typeof raw.rationale !== 'string'
    ) return []
    return [{
      facet: raw.facet,
      status: raw.status as ComparisonMatrixRow['status'],
      supporting_count: raw.supporting_count,
      conflicting_count: raw.conflicting_count,
      independent_origin_count: raw.independent_origin_count,
      supporting_evidence_ids: supporting,
      conflicting_evidence_ids: conflicting,
      rationale: raw.rationale,
    }]
  }).slice(0, 100)
}

export function chartPoints(view: VisualizationView): ChartPoint[] {
  if (!['bar', 'line', 'scatter'].includes(view.kind)) return []
  const points = isRecord(view.dataset) ? view.dataset.points : undefined
  if (!Array.isArray(points)) return []
  const parsed = points.flatMap((raw) => {
    if (!isRecord(raw)) return []
    const evidenceIds = stringArray(raw.evidence_ids)
    if (
      typeof raw.id !== 'string' || typeof raw.label !== 'string' ||
      typeof raw.value !== 'number' || !Number.isFinite(raw.value) ||
      !(raw.unit === null || typeof raw.unit === 'string') ||
      !(raw.series === null || typeof raw.series === 'string') ||
      evidenceIds === null || evidenceIds.length === 0 ||
      !['direct', 'aggregate', 'difference', 'ratio', 'unit_conversion'].includes(String(raw.transform)) ||
      typeof raw.transform_note !== 'string'
    ) return []
    return [{
      id: raw.id,
      label: raw.label,
      value: raw.value,
      unit: raw.unit as string | null,
      series: raw.series as string | null,
      evidence_ids: evidenceIds,
      transform: raw.transform as ChartPoint['transform'],
      transform_note: raw.transform_note,
    }]
  }).slice(0, Math.min(view.approved_spec.max_points, 200))
  const units = new Set(parsed.map((point) => point.unit).filter(Boolean))
  return units.size <= 1 ? parsed : []
}

export function timelineEvents(view: VisualizationView): TimelineEvent[] {
  if (view.kind !== 'timeline') return []
  const events = isRecord(view.dataset) ? view.dataset.events : undefined
  if (!Array.isArray(events)) return []
  return events.flatMap((raw) => {
    if (!isRecord(raw)) return []
    const evidenceIds = stringArray(raw.evidence_ids)
    if (
      typeof raw.id !== 'string' || typeof raw.label !== 'string' ||
      typeof raw.event_at !== 'string' || Number.isNaN(Date.parse(raw.event_at)) ||
      typeof raw.source_id !== 'string' || evidenceIds === null ||
      typeof raw.uncertainty !== 'string'
    ) return []
    return [{
      id: raw.id,
      label: raw.label,
      event_at: raw.event_at,
      source_id: raw.source_id,
      evidence_ids: evidenceIds,
      uncertainty: raw.uncertainty,
    }]
  }).sort((a, b) => Date.parse(a.event_at) - Date.parse(b.event_at)).slice(0, 200)
}

export function evidenceGraph(view: VisualizationView): { nodes: EvidenceGraphNode[]; edges: EvidenceGraphEdge[] } {
  if (view.kind !== 'evidence_map') return { nodes: [], edges: [] }
  const nodesRaw = isRecord(view.dataset) ? view.dataset.nodes : undefined
  const edgesRaw = isRecord(view.dataset) ? view.dataset.edges : undefined
  if (!Array.isArray(nodesRaw) || !Array.isArray(edgesRaw)) return { nodes: [], edges: [] }
  const nodes = nodesRaw.flatMap((raw) => {
    if (!isRecord(raw)) return []
    if (
      typeof raw.id !== 'string' || !['claim', 'evidence', 'source'].includes(String(raw.kind)) || typeof raw.label !== 'string' ||
      !(raw.evidence_id === null || typeof raw.evidence_id === 'string') ||
      !(raw.source_id === null || typeof raw.source_id === 'string') ||
      !(raw.support_status === null || typeof raw.support_status === 'string')
    ) return []
    return [{
      id: raw.id,
      kind: raw.kind as EvidenceGraphNode['kind'],
      label: raw.label,
      evidence_id: raw.evidence_id as string | null,
      source_id: raw.source_id as string | null,
      support_status: raw.support_status as string | null,
    }]
  }).slice(0, 100)
  const nodeIds = new Set(nodes.map((node) => node.id))
  const edges = edgesRaw.flatMap((raw) => {
    if (!isRecord(raw)) return []
    if (
      typeof raw.id !== 'string' || typeof raw.source !== 'string' || typeof raw.target !== 'string' ||
      !nodeIds.has(raw.source) || !nodeIds.has(raw.target) ||
      !['supports', 'contradicts', 'contextualizes', 'originates_from'].includes(String(raw.relation)) ||
      !(raw.evidence_id === null || typeof raw.evidence_id === 'string') || typeof raw.rationale !== 'string'
    ) return []
    return [{
      id: raw.id,
      source: raw.source,
      target: raw.target,
      relation: raw.relation as EvidenceGraphEdge['relation'],
      evidence_id: raw.evidence_id as string | null,
      rationale: raw.rationale,
    }]
  }).slice(0, 200)
  return { nodes, edges }
}
