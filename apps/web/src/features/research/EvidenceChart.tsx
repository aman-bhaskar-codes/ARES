import { useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import { AriaComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer, SVGRenderer } from 'echarts/renderers'
import type { VisualizationView } from '../../lib/api/types'
import { chartPoints } from './visualizationData'

echarts.use([BarChart, LineChart, ScatterChart, AriaComponent, GridComponent, TooltipComponent, CanvasRenderer, SVGRenderer])

export default function EvidenceChart({ visualization, onEvidence }: { visualization: VisualizationView; onEvidence: (id: string) => void }) {
  const root = useRef<HTMLDivElement>(null)
  const points = useMemo(() => chartPoints(visualization), [visualization])

  useEffect(() => {
    if (!root.current || points.length < 2 || !['bar', 'line', 'scatter'].includes(visualization.kind)) return
    const instance = echarts.init(root.current, undefined, { renderer: visualization.approved_spec.renderer })
    const option = {
      aria: { enabled: true, decal: { show: true }, description: `${visualization.title}. ${visualization.description}` },
      animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      grid: { left: 56, right: 24, top: 24, bottom: 72, containLabel: true },
      tooltip: { show: false },
      xAxis: { type: 'category' as const, data: points.map((point) => point.label), axisLabel: { interval: 0, rotate: points.length > 8 ? 35 : 0 } },
      yAxis: { type: 'value' as const, name: visualization.approved_spec.unit ?? undefined },
      series: [{
        type: visualization.kind as 'bar' | 'line' | 'scatter',
        data: points.map((point) => point.value),
        emphasis: { focus: 'self' as const },
        symbolSize: visualization.kind === 'scatter' ? 11 : undefined,
      }],
    }
    instance.setOption(option)
    instance.on('click', (params) => {
      const index = typeof params.dataIndex === 'number' ? params.dataIndex : -1
      const evidenceId = points[index]?.evidence_ids[0]
      if (evidenceId) onEvidence(evidenceId)
    })
    const resize = () => instance.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      instance.dispose()
    }
  }, [onEvidence, points, visualization.approved_spec.renderer, visualization.approved_spec.unit, visualization.description, visualization.kind, visualization.title])

  if (points.length < 2) return <div className="visual-empty">The validated numeric dataset is unavailable or contains incomparable units.</div>
  return <div ref={root} className="evidence-chart" role="img" aria-label={`${visualization.title}. Select a plotted value to inspect its cited evidence.`}/>
}
