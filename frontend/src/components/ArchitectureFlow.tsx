/** Shared architecture stage nodes; omit arrows for parallel sources or branches. */
export function ArchitectureFlow({ nodes, connected = true }: { nodes: readonly (readonly string[])[]; connected?: boolean }) {
  return <div className="knowledge-architecture-flow">{nodes.map(([title, detail], index) => <div className="knowledge-architecture-flow-item" key={title}>
    {index > 0 && connected && <span className="knowledge-architecture-arrow" aria-hidden="true">→</span>}
    <div className="knowledge-architecture-node"><strong>{title}</strong><small>{detail}</small></div>
  </div>)}</div>
}
