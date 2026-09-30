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
    label: '02 · Retrieval · implemented',
    nodes: [
      ['Question', 'Validate · keyword signals'],
      ['Access scope', 'Server-owned persona groups'],
      ['Hybrid search', 'Lexical + vector on allowed chunks'],
      ['Fusion + rerank', 'Exact citable excerpts'],
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
    <section className="knowledge-architecture-stage planned">
      <h3>03 · Answer and action · planned</h3>
      <div className="knowledge-architecture-split">
        <div><strong>Citable chunks → answer model → citation check → cited answer</strong><small>Read-only path; insufficient support leads to abstention.</small></div>
        <div><strong>Action proposal → policy check → approval → mock executor</strong><small>Only the action path has side effects; approval is recorded before execution.</small></div>
      </div>
    </section>
    <p className="knowledge-architecture-footnote">Both retrieval paths use the same ACL scope before candidate scoring. Mock embedding evals exercise the wiring; real-model retrieval quality remains unverified.</p>
  </div>
}
