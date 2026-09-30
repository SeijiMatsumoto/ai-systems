import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
} from '@xyflow/react'
import type { Edge, Node, NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

type SystemNodeData = {
  category: string
  title: string
  detail: string
  tone?: 'model' | 'gate' | 'outcome' | 'support'
}

type SystemNode = Node<SystemNodeData, 'system'>

function DiagramNode({ data }: NodeProps<SystemNode>) {
  return (
    <div className={`incident-diagram-node incident-diagram-node-${data.tone ?? 'default'}`}>
      <Handle type="target" id="left" position={Position.Left} className="incident-diagram-handle" />
      <Handle type="target" id="top" position={Position.Top} className="incident-diagram-handle" />
      <Handle type="target" id="bottom-right-in" position={Position.Bottom} className="incident-diagram-handle" style={{ left: '78%' }} />
      <Handle type="target" id="top-left-in" position={Position.Top} className="incident-diagram-handle" style={{ left: '22%' }} />
      <span>{data.category}</span>
      <strong>{data.title}</strong>
      <small>{data.detail}</small>
      <Handle type="source" id="right" position={Position.Right} className="incident-diagram-handle" />
      <Handle type="source" id="bottom" position={Position.Bottom} className="incident-diagram-handle" />
      <Handle type="source" id="bottom-left-out" position={Position.Bottom} className="incident-diagram-handle" style={{ left: '22%' }} />
      <Handle type="source" id="top-right-out" position={Position.Top} className="incident-diagram-handle" style={{ left: '78%' }} />
    </div>
  )
}

const nodeTypes = { system: DiagramNode }

function node(id: string, x: number, y: number, data: SystemNodeData): SystemNode {
  return { id, type: 'system', position: { x, y }, data, draggable: false }
}

const nodes: SystemNode[] = [
  node('telemetry', 24, 60, { category: 'CONTINUOUS INPUT', title: 'Synthetic log stream', detail: 'Replay logs in timestamp order' }),
  node('detector', 258, 60, { category: 'DETERMINISTIC', title: 'Candidate detection', detail: 'Group, correlate, apply threshold' }),
  node('classifier', 492, 60, { category: 'MODEL · JEV', title: 'Incident classification', detail: 'Judge candidate evidence', tone: 'model' }),
  node('controller', 726, 60, { category: 'DETERMINISTIC', title: 'Run controller', detail: 'Apply limits and scope evidence', tone: 'gate' }),
  node('support', 1194, 60, { category: 'CROSS-CUTTING', title: 'Run state & tracing', detail: 'llm_runs · Logfire', tone: 'support' }),
  node('triage', 492, 258, { category: 'CLASSIFIER OUTCOME', title: 'Dismiss or review', detail: 'No investigation launched', tone: 'outcome' }),
  node('investigator', 726, 258, { category: 'MODEL · AGENT', title: 'Investigator', detail: 'Choose query or draft report', tone: 'model' }),
  node('verifier', 960, 258, { category: 'DETERMINISTIC', title: 'Citation verifier', detail: 'Resolve evidence IDs and scope' }),
  node('review', 1194, 258, { category: 'OUTPUT', title: 'Engineer review', detail: 'Approve or request changes on a cited draft', tone: 'outcome' }),
  node('tools', 726, 492, { category: 'SCOPED TOOL SET', title: 'Telemetry query tools', detail: 'Read-only logs, metrics, traces, changes', tone: 'gate' }),
]

const arrow = { type: MarkerType.ArrowClosed, width: 15, height: 15, color: '#7c9184' }
const standard = { stroke: '#7c9184', strokeWidth: 1.7 }
const model = { stroke: '#5b7799', strokeWidth: 1.9 }

function edge(id: string, source: string, target: string, options: Partial<Edge> = {}): Edge {
  return {
    id,
    source,
    target,
    type: 'smoothstep',
    sourceHandle: 'right',
    targetHandle: 'left',
    markerEnd: arrow,
    style: standard,
    ...options,
  }
}

const edges: Edge[] = [
  edge('telemetry-detector', 'telemetry', 'detector'),
  edge('detector-classifier', 'detector', 'classifier', { label: 'candidate' }),
  edge('classifier-controller', 'classifier', 'controller', { style: model }),
  edge('classifier-triage', 'classifier', 'triage', { sourceHandle: 'bottom', targetHandle: 'top' }),
  edge('controller-investigator', 'controller', 'investigator', { sourceHandle: 'bottom', targetHandle: 'top', style: model }),
  edge('investigator-verifier', 'investigator', 'verifier', { label: 'draft', style: model }),
  edge('verifier-review', 'verifier', 'review'),
  edge('investigator-tools', 'investigator', 'tools', {
    type: 'straight', sourceHandle: 'bottom-left-out', targetHandle: 'top-left-in',
    label: 'query', style: model,
  }),
  edge('tools-investigator', 'tools', 'investigator', {
    type: 'straight', sourceHandle: 'top-right-out', targetHandle: 'bottom-right-in',
    label: 'evidence', style: model, markerEnd: { ...arrow, color: '#5b7799' },
  }),
  edge('controller-support', 'controller', 'support', {
    style: { stroke: '#aab7ae', strokeWidth: 1.2, strokeDasharray: '4 5' },
    markerEnd: undefined,
  }),
]

export default function IncidentSystemDiagram() {
  return (
    <div className="incident-diagram" role="region" aria-label="Incident architecture diagram. The synthetic log stream continuously feeds deterministic candidate detection. Only candidates enter Jev classification and run control. The investigator loops through scoped telemetry tools before citation verification and engineer review. Run state and tracing are cross-cutting systems.">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onInit={(instance) => {
          void instance.fitView({ padding: 0.02 }).then(() => {
            const viewport = instance.getViewport()
            void instance.setViewport({ ...viewport, x: 28 })
          })
        }}
        minZoom={0.45}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} color="#dce6de" gap={22} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
