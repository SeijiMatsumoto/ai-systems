import { MarkerType } from '@xyflow/react'
import ArchitectureGraph from './components/ArchitectureGraph'
import { box, down, link, memory } from './components/architectureGraphData'

const nodes = [
  box('client', 0, 210, 'CLIENT', 'Customer chat', 'Messages · answers · confirmation cards'),
  box('gateway', 300, 210, 'REQUEST BOUNDARY', 'Support API + routing', 'Identity · prechecks → Jev intent → app gate', 'gate'),
  box('agent', 600, 210, 'MODEL + HARNESS', 'Support orchestrator', 'Bounded agent · scoped tools · subject resolution', 'model'),
  box('verify', 900, 210, 'VERIFICATION', 'Evidence + output gate', 'Citation/scope checks → Jev grounding', 'gate'),
  box('answer', 1200, 210, 'RESPONSE', 'Answer or clarification', 'Cited facts · missing details · safe stop', 'outcome'),
  box('state', 600, 0, 'PERSISTENT STATE', 'Conversation + run store', 'Subjects · pending tasks · outputs · audit trail', 'support'),
  box('policy', 300, 450, 'READ-ONLY KNOWLEDGE', 'Policy retrieval', 'Lexical + vector search · checked policy cache'),
  box('account', 600, 450, 'AUTHORITATIVE RECORDS', 'Order + catalog tools', 'Customer-scoped reads · fresh mutable state'),
  box('actions', 900, 450, 'CONFIRMED ACTIONS', 'Order change service', 'Proposal → confirm → fresh checks → atomic write', 'gate'),
  box('human', 1200, 450, 'HUMAN HANDOFF', 'Support case queue', 'Refunds · returns · warranty · blocked changes', 'outcome'),
]
const edges = [
  link('client', 'gateway'), link('gateway', 'agent'), link('agent', 'verify'), link('verify', 'answer'),
  link('state', 'agent', 'load / checkpoint', { ...down, ...memory, markerStart: { type: MarkerType.ArrowClosed, color: '#aab7ae' } }),
  link('agent', 'policy', 'policy query / evidence', { sourceHandle: 'out-bottom-left', targetHandle: 'top', markerStart: { type: MarkerType.ArrowClosed, color: '#7c9184' } }),
  link('agent', 'account', 'lookup / current facts', { ...down, markerStart: { type: MarkerType.ArrowClosed, color: '#7c9184' } }),
  link('verify', 'actions', 'checked proposal', down),
  link('verify', 'human', 'review request', down),
  link('gateway', 'human', 'explicit human request', { sourceHandle: 'out-top', targetHandle: 'right' }),
  link('actions', 'human', 'stale / blocked', { sourceHandle: 'out-bottom', targetHandle: 'bottom' }),
]
export default function SupportSystemDiagram() {
  return <ArchitectureGraph nodes={nodes} edges={edges}
    description="Customer Support system design: a scoped API validates requests before Jev routing. A bounded orchestrator reads policy and current account records, then verifies answers or proposals. Customer-confirmed order changes and human-review cases are separate branches. Conversation state and the audit trail persist between messages."
    note="Policy explains the rules; current order records establish account facts. The orchestrator can repeat scoped reads before producing a result. Natural-language approval never executes a change: the saved confirmation card does, after fresh ownership/state/policy checks and idempotency protection. Refunds always go to human review. Stores and writes are synthetic demo implementations." />
}
