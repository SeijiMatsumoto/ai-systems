import { useEffect } from 'react'
import { Background, BackgroundVariant, Controls, Handle, Position, ReactFlow, useNodesInitialized, useReactFlow, useStore } from '@xyflow/react'
import type { Edge, NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import type { BoxNode } from './architectureGraphData'

function DiagramBox({ data }: NodeProps<BoxNode>) {
  return <div className={`incident-diagram-node incident-diagram-node-${data.tone ?? 'default'}`}>
    <Handle type="target" id="left" position={Position.Left} className="incident-diagram-handle" />
    <Handle type="target" id="top" position={Position.Top} className="incident-diagram-handle" />
    <Handle type="target" id="bottom" position={Position.Bottom} className="incident-diagram-handle" />
    <Handle type="target" id="right" position={Position.Right} className="incident-diagram-handle" />
    <span>{data.category}</span><strong>{data.title}</strong><small>{data.detail}</small>
    <Handle type="source" id="out-right" position={Position.Right} className="incident-diagram-handle" />
    <Handle type="source" id="out-left" position={Position.Left} className="incident-diagram-handle" />
    <Handle type="source" id="out-bottom-left" position={Position.Bottom} style={{ left: '22%' }} className="incident-diagram-handle" />
    <Handle type="source" id="out-bottom" position={Position.Bottom} className="incident-diagram-handle" />
    <Handle type="source" id="out-top" position={Position.Top} className="incident-diagram-handle" />
  </div>
}
function FitDiagram() {
  const initialized = useNodesInitialized()
  const pane = useStore((state) => state.domNode)
  const panZoom = useStore((state) => state.panZoom)
  const { fitView } = useReactFlow()
  useEffect(() => {
    if (!pane || !panZoom) return
    let frame = 0
    const fit = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => { void fitView({ padding: 0.1 }) })
    }
    const observer = new ResizeObserver(fit)
    observer.observe(pane)
    fit()
    return () => { observer.disconnect(); cancelAnimationFrame(frame) }
  }, [initialized, pane, panZoom, fitView])
  return null
}
const nodeTypes = { system: DiagramBox }
export default function ArchitectureGraph({ nodes, edges, description, note }: { nodes: BoxNode[]; edges: Edge[]; description: string; note: string }) {
  return <div className="system-architecture-graph">
    <p className="architecture-modal-note">{note}</p>
    <div className="incident-diagram" role="region" aria-label={description}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} minZoom={0.25} maxZoom={1.8} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} proOptions={{ hideAttribution: true }}>
        <FitDiagram />
        <Background variant={BackgroundVariant.Dots} color="#dce6de" gap={22} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
    <p className="architecture-graph-legend">Blue: model judgment · Amber: deterministic boundary · Dashed: saved context or evidence · Arrows: request, evidence or execution flow. Drag to pan; use the controls to zoom.</p>
  </div>
}
