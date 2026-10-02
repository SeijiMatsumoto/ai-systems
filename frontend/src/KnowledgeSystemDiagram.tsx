import { MarkerType } from '@xyflow/react'
import ArchitectureGraph from './components/ArchitectureGraph'
import { box, down, link, memory } from './components/architectureGraphData'

const nodes = [
  box('documents', 0, 0, 'SOURCE SYSTEMS', 'Internal documents', 'Policies · knowledge documents · support tickets'),
  box('ingestion', 300, 0, 'INGESTION PIPELINE', 'Chunk + embed changes', 'Parse · version · content hash · exact locators', 'gate'),
  box('index', 600, 0, 'KNOWLEDGE STORE', 'Text + vector index', 'Versioned chunks · embeddings · document ACLs', 'support'),
  box('client', 0, 230, 'CLIENT', 'Employee assistant', 'Question · cited answer · approval controls'),
  box('gateway', 300, 230, 'REQUEST BOUNDARY', 'Identity + intent gateway', 'Prechecks → optional Jev → app decision', 'gate'),
  box('retrieval', 600, 230, 'ACCESS-CONTROLLED RAG', 'Hybrid retrieval', 'ACL filter → lexical + vector search → rerank', 'gate'),
  box('answer', 900, 230, 'MODEL + VERIFICATION', 'Cited answer service', 'Generate → citation checks → Jev grounding', 'model'),
  box('output', 1200, 230, 'RESPONSE', 'Answer or abstention', 'Verified Markdown answer · grouped sources', 'outcome'),
  box('state', 300, 460, 'PERSISTENT STATE', 'Chat + audit store', 'Bounded history · runs · evidence · decisions', 'support'),
  box('actions', 900, 460, 'APPROVAL-GATED ACTION', 'Support follow-up service', 'Typed proposal → approve → recheck → local task', 'gate'),
]
const edges = [
  link('documents', 'ingestion'), link('ingestion', 'index'),
  link('client', 'gateway'), link('gateway', 'retrieval'),
  link('index', 'retrieval', 'authorized index reads', { ...down, ...memory }),
  link('retrieval', 'answer', 'selected excerpts'), link('answer', 'output'),
  link('retrieval', 'actions', 'action intent + ticket evidence', { sourceHandle: 'out-bottom', targetHandle: 'left' }),
  link('state', 'gateway', 'load / save context', { sourceHandle: 'out-top', targetHandle: 'bottom', ...memory, markerStart: { type: MarkerType.ArrowClosed, color: '#aab7ae' } }),
  link('answer', 'state', 'answer + evidence', { sourceHandle: 'out-bottom-left', targetHandle: 'top', type: 'default', ...memory }),
  link('actions', 'state', 'proposal / decision / task', { sourceHandle: 'out-bottom', targetHandle: 'bottom', ...memory }),
]
export default function KnowledgeSystemDiagram() {
  return <ArchitectureGraph nodes={nodes} edges={edges}
    description="Internal Knowledge and Action system design: sources are chunked and embedded into a versioned text/vector index. Request checks precede conditional Jev intent. Authorized hybrid retrieval supplies evidence to a verified answer service or an approval-gated support follow-up service. Chat context, evidence and decisions are persisted."
    note="Ingestion is separate from request-time retrieval. ACL filtering happens before both lexical and vector scoring. Prior messages resolve context but are not evidence. Only the supported follow-up task can be proposed; approval rechecks approver, requester access, action type and evidence before an idempotent write. Identities are simulated and mock vectors do not establish semantic retrieval quality." />
}
