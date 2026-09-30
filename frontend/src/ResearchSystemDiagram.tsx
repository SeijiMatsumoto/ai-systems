function Box({ x, y, category, title, detail, tone = 'default' }: {
  x: number
  y: number
  category: string
  title: string
  detail: string
  tone?: 'default' | 'model' | 'store' | 'gate'
}) {
  return (
    <g className={`research-map-box research-map-box-${tone}`}>
      <rect x={x} y={y} width={160} height={84} rx="9" />
      <text x={x + 12} y={y + 20} className="research-map-category">{category}</text>
      <text x={x + 12} y={y + 42} className="research-map-title">{title}</text>
      <text x={x + 12} y={y + 64} className="research-map-detail">{detail}</text>
    </g>
  )
}

export default function ResearchSystemDiagram() {
  return (
    <div className="research-system-diagram" role="region" aria-label="Research architecture diagram. A deterministic query precheck runs before Jev. Application thresholds decide accept, reject, or fallback. The bounded agent calls scoped tools, source filters return evidence to the agent, and the agent can repeat this loop before drafting. Only the draft proceeds to citation provenance and grounding checks. Ordered steps and the briefing are persisted before streaming.">
      <svg viewBox="0 0 1480 365" aria-hidden="true">
        <defs>
          <marker id="research-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" /></marker>
          <marker id="research-loop-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#5b7799" /></marker>
        </defs>
        <g className="research-map-edges" markerEnd="url(#research-arrow)">
          {[170, 355, 540, 725, 910, 1095, 1280].map((x) => <path key={x} d={`M${x} 72 H${x + 21}`} />)}
          <path d="M640 114 V226" />
          <path d="M1195 114 V226" />
          <path d="M1380 114 V226" />
        </g>
        <g className="research-map-loop" markerEnd="url(#research-loop-arrow)">
          <path d="M805 114 V226" />
          <path d="M910 272 H931" />
          <path d="M1010 230 V164 H865 V118" />
        </g>
        <Box x={10} y={30} category="TYPED INPUT" title="Research request" detail="Company · question · run cutoff" />
        <Box x={195} y={30} category="DETERMINISTIC" title="Query precheck" detail="Normalize · keywords · reject" tone="gate" />
        <Box x={380} y={30} category="MODEL · JEV" title="Request judgment" detail="Relevance · instruction risk" tone="model" />
        <Box x={565} y={30} category="APP DECISION" title="After Jev" detail="Threshold · reject · fallback" tone="gate" />
        <Box x={750} y={30} category="MODEL · AGENT" title="Research agent" detail="Choose source or draft" tone="model" />
        <Box x={935} y={30} category="CITATION PRECHECK" title="Provenance checks" detail="IDs · scope · exact locators" tone="gate" />
        <Box x={1120} y={30} category="MODEL CLASSIFIER" title="Grounding judgment" detail="Claim vs verified evidence" tone="model" />
        <Box x={1305} y={30} category="OUTPUT" title="Cited briefing" detail="Retained findings · limits" />
        <Box x={565} y={230} category="APP BRANCH" title="Reject or fallback" detail="Classifier if Jev uncertain" tone="store" />
        <Box x={750} y={230} category="SCOPED TOOLS" title="Source selection" detail="Filings · Yahoo · Tavily" />
        <Box x={935} y={230} category="DETERMINISTIC" title="Source filters" detail="Date · company · selected URLs" tone="gate" />
        <Box x={1120} y={230} category="APP DECISION" title="Repair or exclude" detail="Rebuild from retained findings" tone="gate" />
        <Box x={1305} y={230} category="PERSISTENCE" title="Run and steps" detail="Save before SSE stream" tone="store" />
        <text x="748" y="174" className="research-map-edge-label">tool calls ↓</text>
        <text x="877" y="152" className="research-map-edge-label">filtered evidence ↰</text>
        <text x="1132" y="174" className="research-map-edge-label">unsupported ↓</text>
        <text x="16" y="350" className="research-map-footnote">The agent can repeat the tool loop before drafting. Keyword signals inform Jev; application code owns the decisions and citation checks.</text>
      </svg>
    </div>
  )
}
