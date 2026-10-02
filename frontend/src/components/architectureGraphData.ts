import { MarkerType } from '@xyflow/react'
import type { Edge, Node } from '@xyflow/react'

export type BoxData = { category: string; title: string; detail: string; tone?: 'model' | 'gate' | 'outcome' | 'support' }
export type BoxNode = Node<BoxData, 'system'>

export function box(id: string, x: number, y: number, category: string, title: string, detail: string, tone?: BoxData['tone']): BoxNode {
  return { id, type: 'system', position: { x, y }, data: { category, title, detail, tone }, draggable: false }
}
export function link(source: string, target: string, label?: string, options: Partial<Edge> = {}): Edge {
  return { id: `${source}-${target}-${label ?? ''}`, source, target, label, type: 'smoothstep', sourceHandle: 'out-right', targetHandle: 'left', markerEnd: { type: MarkerType.ArrowClosed, color: '#7c9184' }, style: { stroke: '#7c9184', strokeWidth: 1.7 }, ...options }
}
export const down = { sourceHandle: 'out-bottom', targetHandle: 'top' }
export const memory = { style: { stroke: '#aab7ae', strokeWidth: 1.4, strokeDasharray: '5 5' } }
