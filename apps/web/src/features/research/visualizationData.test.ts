import { describe, expect, it } from 'vitest'
import type { VisualizationView } from '../../lib/api/types'
import { chartPoints } from './visualizationData'

const chart = (label = 'North'): VisualizationView => ({
  id: 'visualization-1', run_id: 'run-1', dataset_id: 'dataset-1', kind: 'bar', title: 'Sourced values', description: '', schema_version: 1,
  dataset: { points: [{ id: 'p1', label, value: 12, unit: 'km', series: null, evidence_ids: ['e1'], transform: 'direct', transform_note: 'cited cell' }, { id: 'p2', label: 'South', value: 8, unit: 'km', series: null, evidence_ids: ['e2'], transform: 'direct', transform_note: 'cited cell' }] },
  approved_spec: { kind: 'bar', x_field: 'label', y_field: 'value', series_field: null, unit: 'km', renderer: 'svg', max_points: 200, allow_download_csv: true, accessible_table: true },
  data_lineage: [], export_metadata: {}, created_at: '2026-10-05T00:00:00Z',
})

describe('visualization data safety', () => {
  it('accepts finite comparable evidence-backed chart points', () => {
    expect(chartPoints(chart())).toHaveLength(2)
  })

  it('rejects mixed units instead of plotting incomparable values', () => {
    const view = chart()
    const points = view.dataset.points as Array<Record<string, unknown>>
    points[1].unit = 'mph'
    expect(chartPoints(view)).toEqual([])
  })
})
