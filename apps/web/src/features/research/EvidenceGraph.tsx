import { useMemo, type ComponentType } from 'react'
import { Background, Controls, ReactFlow as XYReactFlow, type Edge, type EdgeMouseHandler, type Node, type NodeMouseHandler, type ReactFlowProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { VisualizationView } from '../../lib/api/types'
import { evidenceGraph } from './visualizationData'

type GraphNodeData = { label: string; evidenceId: string | null; kind: string }
type GraphEdgeData = { evidenceId: string | null; relation: string }

// @xyflow/react 12.12 has a callable generic component, but TypeScript 7 currently
// resolves the re-exported symbol as the package namespace under Bundler resolution.
// Keep its public ReactFlowProps contract and narrow only the JSX constructor surface.
const ReactFlowComponent = XYReactFlow as unknown as ComponentType<ReactFlowProps<Node<GraphNodeData>, Edge<GraphEdgeData>>>

export default function EvidenceGraph({ visualization, onEvidence }: { visualization: VisualizationView; onEvidence: (id: string) => void }) {
  const graph = useMemo(() => evidenceGraph(visualization), [visualization])
  const { nodes, edges } = useMemo(() => {
    const laneX: Record<string, number> = { claim: 0, evidence: 330, source: 660 }
    const laneIndex: Record<string, number> = { claim: 0, evidence: 0, source: 0 }
    const flowNodes: Array<Node<GraphNodeData>> = graph.nodes.map((node) => {
      const row = laneIndex[node.kind]++
      return {
        id: node.id,
        position: { x: laneX[node.kind] ?? 0, y: row * 118 },
        data: { label: node.label, evidenceId: node.evidence_id, kind: node.kind },
        draggable: false,
        selectable: true,
        style: {
          width: 240,
          borderRadius: 10,
          border: '1px solid var(--line)',
          background: 'var(--surface)',
          color: 'var(--ink)',
          fontSize: 11,
          lineHeight: 1.35,
          padding: 10,
        },
      }
    })
    const flowEdges: Array<Edge<GraphEdgeData>> = graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.relation.replaceAll('_', ' '),
      data: { evidenceId: edge.evidence_id, relation: edge.relation },
      selectable: true,
      animated: false,
    }))
    return { nodes: flowNodes, edges: flowEdges }
  }, [graph])

  const onNodeClick: NodeMouseHandler<Node<GraphNodeData>> = (_, node) => { if (node.data.evidenceId) onEvidence(node.data.evidenceId) }
  const onEdgeClick: EdgeMouseHandler<Edge<GraphEdgeData>> = (_, edge) => { if (edge.data?.evidenceId) onEvidence(edge.data.evidenceId) }

  if (!nodes.length || !edges.length) return <div className="visual-empty">No bounded claim–evidence neighborhood is available for this run.</div>
  return (
    <div className="evidence-graph" aria-label="Interactive evidence relationship map">
      <ReactFlowComponent
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        minZoom={0.35}
        maxZoom={1.8}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        proOptions={{ hideAttribution: false }}
      >
        <Background gap={20}/>
        <Controls showInteractive={false}/>
      </ReactFlowComponent>
    </div>
  )
}
