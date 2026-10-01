const stages = [
  {
    label: '01 · Indexing · implemented with mock embeddings',
    nodes: [
      ['Sources', 'Versioned docs · tickets · policies'],
      ['Parse + chunk', 'Exact source offsets'],
      ['Embed changes', 'Model + content version'],
      ['Local index', 'Text · vectors · ACL metadata'],
    ],
  },
  {
    label: '02 · Request + intent · implemented',
    nodes: [
      ['Request checks', 'Schema · length · normalization'],
      ['Action signals', 'Deterministic keyword patterns'],
      ['Jev intent', 'Only when signals are present'],
      ['App threshold', 'Read-only answer or action branch'],
    ],
  },
  {
    label: '03 · ACL retrieval · implemented',
    nodes: [
      ['Access scope', 'Server-owned persona groups'],
      ['Hybrid search', 'Lexical + vector on allowed chunks'],
      ['Fusion + rerank', 'Exact citable excerpts'],
      ['Read-only answer', 'Typed claims · provenance · Jev'],
    ],
  },
]

function FlowRow({ nodes }: { nodes: string[][] }) {
  return <div className="knowledge-architecture-flow">
    {nodes.map(([title, detail], index) => <div className="knowledge-architecture-flow-item" key={title}>
      {index > 0 && <span className="knowledge-architecture-arrow" aria-hidden="true">→</span>}
      <div className="knowledge-architecture-node"><strong>{title}</strong><small>{detail}</small></div>
    </div>)}
  </div>
}

export default function KnowledgeSystemDiagram() {
  return <div className="knowledge-architecture" role="region" aria-label="Knowledge and Action architecture">
    {stages.map((stage) => <section className="knowledge-architecture-stage" key={stage.label}>
      <h3>{stage.label}</h3>
      <FlowRow nodes={stage.nodes} />
    </section>)}
    <section className="knowledge-architecture-stage">
      <h3>Read-only branch · implemented</h3>
      <div className="knowledge-architecture-split">
        <div><strong>Selected passages → typed Markdown claims → citation provenance</strong><small>Only authorized, frozen excerpts reach the model. Answers support paragraphs, bullets, and numbered steps.</small></div>
        <div><strong>Deterministic citation checks → Jev grounding → saved answer</strong><small>Citation chips remain attached to claims; rejected or unsupported claims abstain.</small></div>
      </div>
    </section>
    <section className="knowledge-architecture-stage">
      <h3>04 · Approval-gated action · implemented</h3>
      <div className="knowledge-architecture-split">
        <div><strong>Keyword signals → Jev intent → ACL-scoped ticket → typed proposal</strong><small>Deterministic request checks precede Jev. The proposal model sees only authorized support-ticket evidence and cannot create a task.</small></div>
        <div><strong>Approver check → execution-time policy recheck → idempotent local task</strong><small>One synthetic support-follow-up type; denied, stale, rejected, and repeated decisions are saved.</small></div>
      </div>
    </section>
    <p className="knowledge-architecture-footnote">Both retrieval paths use the same ACL scope before candidate scoring. Mock embedding evals exercise the wiring; real-model retrieval quality remains unverified.</p>
  </div>
}
