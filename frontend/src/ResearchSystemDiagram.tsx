function Box({ x, y, category, title, detail, tone = 'default', width = 160 }: {
  x: number
  y: number
  category: string
  title: string
  detail: string
  tone?: 'default' | 'model' | 'store'
  width?: number
}) {
  return (
    <g className={`research-map-box research-map-box-${tone}`}>
      <rect x={x} y={y} width={width} height={80} rx="9" />
      <text x={x + 12} y={y + 20} className="research-map-category">{category}</text>
      <text x={x + 12} y={y + 42} className="research-map-title">{title}</text>
      <text x={x + 12} y={y + 62} className="research-map-detail">{detail}</text>
    </g>
  )
}

export default function ResearchSystemDiagram() {
  return (
    <div className="research-system-diagram" role="region" aria-label="Research architecture diagram. A Jev request gate precedes a bounded single agent. The agent loops through scoped filing, financial, and Tavily tools. Application code verifies citations and saves the briefing with ordered run steps.">
      <svg viewBox="0 0 920 335" aria-hidden="true">
        <defs>
          <marker id="research-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" /></marker>
        </defs>
        <g className="research-map-edges" markerEnd="url(#research-arrow)">
          <path d="M170 66 H191" />
          <path d="M355 66 H376" />
          <path d="M540 66 H561" />
          <path d="M725 66 H746" />
          <path d="M418 108 V210" />
          <path d="M499 210 V108" />
          <path d="M645 108 V210" />
          <path d="M270 108 V210" />
        </g>
        <Box x={10} y={26} category="INPUT" title="Research request" detail="Company · question · as-of" />
        <Box x={195} y={26} category="MODEL · JEV" title="Request gate" detail="Typed yes/no decisions" tone="model" />
        <Box x={380} y={26} category="MODEL · AGENT" title="Research agent" detail="Choose source or draft" tone="model" />
        <Box x={565} y={26} category="APPLICATION" title="Evidence checks" detail="Resolve IDs · ground · repair" />
        <Box x={750} y={26} category="OUTPUT" title="Cited briefing" detail="Findings · limits · evidence" />
        <Box x={380} y={215} category="SCOPED TOOLS" title="Source selection" detail="Filings · Yahoo · Tavily" />
        <Box x={565} y={215} category="PERSISTENCE" title="Run and steps" detail="llm_runs · research_runs" tone="store" />
        <Box x={195} y={215} category="GATE OUTCOME" title="Reject or fallback" detail="Application thresholds" tone="store" />
        <text x="394" y="165" className="research-map-edge-label">query ↓</text>
        <text x="486" y="165" className="research-map-edge-label">↑ evidence</text>
        <text x="652" y="165" className="research-map-edge-label">save</text>
        <text x="16" y="316" className="research-map-footnote">Research steps are persisted before streaming. Logfire can supplement the walkthrough when tracing is enabled.</text>
      </svg>
    </div>
  )
}
