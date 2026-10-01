import { ArchitectureFlow } from './components/ArchitectureFlow'

const stages = [
  {
    label: '01 · Ingest and index',
    nodes: [
      ['Synthetic sources', 'Policies · documents · support tickets'],
      ['Parse + chunk', 'Versioned text · exact source offsets'],
      ['Embed changes', 'Content hash · embedding model version'],
      ['Local index', 'Vectors · text · server-owned ACLs'],
    ],
  },
  {
    label: '02 · Check request and classify intent',
    nodes: [
      ['Deterministic checks', 'Validate · normalize · bound input'],
      ['Action signals', 'Keyword patterns before model calls'],
      ['Jev intent', 'Runs only when action signals are present'],
      ['App decision', 'Threshold chooses answer or action path'],
    ],
  },
  {
    label: '03 · Retrieve authorized evidence',
    nodes: [
      ['Resolve access', 'Server-owned persona groups'],
      ['Lexical search', 'BM25-style term scoring'],
      ['Vector search', 'Query embedding · authorized vectors only'],
      ['Fuse + rerank', 'Bounded candidates · exact excerpts'],
    ],
  },
]

export default function KnowledgeSystemDiagram() {
  return <div className="knowledge-architecture" role="region" aria-label="Internal Knowledge and Action architecture">
    {stages.map((stage) => <section className="knowledge-architecture-stage" key={stage.label}>
      <h3>{stage.label}</h3>
      <ArchitectureFlow nodes={stage.nodes} />
    </section>)}

    <section className="knowledge-architecture-stage">
      <h3>04 · Answer path</h3>
      <div className="knowledge-architecture-split">
        <div><strong>Selected passages → typed answer claims</strong><small>The answer model receives only the current question, bounded conversation context, and ACL-authorized excerpts. Prior answers help resolve follow-ups but are not evidence.</small></div>
        <div><strong>Deterministic citation checks → Jev grounding → saved answer</strong><small>Application code verifies evidence IDs and exact locators first. Jev then checks claim support; unsupported or unverified answers abstain. The answer and ordered workflow are saved to the shared run history.</small></div>
      </div>
    </section>

    <section className="knowledge-architecture-stage">
      <h3>05 · Action path</h3>
      <div className="knowledge-architecture-split">
        <div><strong>Positive intent → authorized ticket evidence → typed proposal</strong><small>Only the supported follow-up action is available. The proposal model receives authorized support-ticket passages and cannot execute a task.</small></div>
        <div><strong>Simulated approval → policy recheck → idempotent mock task</strong><small>Application policy checks the approver, requester scope, action type, and evidence again at execution. Writes stay in the local demo database; no external task system is called.</small></div>
      </div>
    </section>

    <p className="knowledge-architecture-footnote">The persona picker demonstrates identity selection; it is not real authentication. Both search paths apply ACLs before candidate scoring. The default mock embeddings verify wiring, not semantic retrieval quality.</p>
  </div>
}
