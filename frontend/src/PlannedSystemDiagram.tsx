type Step = { category: string; title: string; detail: string; tone?: 'model' | 'gate' | 'output' }

const designs: Record<string, { summary: string; main: Step[]; branch: Step; branchLabel: string; returnLabel: string; note: string }> = {
  'coding-agent': {
    summary: 'A proposed coding agent searches a scoped fixture repository, edits in an isolated workspace, runs tests, and offers a diff for human review.',
    main: [
      { category: 'REQUEST', title: 'Issue + allowed scope', detail: 'Task and permitted paths' },
      { category: 'DISCOVERY', title: 'Code search', detail: 'Find relevant files and tests' },
      { category: 'MODEL · AGENT', title: 'Edit / test loop', detail: 'Choose next change or stop', tone: 'model' },
      { category: 'RUNTIME GATE', title: 'Scope + test checks', detail: 'Enforce paths and commands', tone: 'gate' },
      { category: 'HUMAN REVIEW', title: 'Proposed diff', detail: 'Patch, tests, risks', tone: 'output' },
    ],
    branch: { category: 'ISOLATED WORKSPACE', title: 'Fixture repository', detail: 'Read, edit, test; no external write' },
    branchLabel: 'tool call', returnLabel: 'file + test result',
    note: 'The runtime owns file permissions and command limits; the model proposes edits but cannot expand its own scope.',
  },
  'customer-support': {
    summary: 'A proposed support agent reads policy and authoritative account state, checks ownership and eligibility, then answers, acts, or escalates.',
    main: [
      { category: 'REQUEST', title: 'Customer message', detail: 'Authenticated conversation' },
      { category: 'SOURCE LOOKUP', title: 'Policy + account', detail: 'Rules and current state' },
      { category: 'MODEL · AGENT', title: 'Answer or propose', detail: 'Cite policy; suggest action', tone: 'model' },
      { category: 'ACTION GATE', title: 'Ownership + policy', detail: 'Check eligibility in code', tone: 'gate' },
      { category: 'OUTPUT', title: 'Answer / handoff', detail: 'Confirmed state or escalation', tone: 'output' },
    ],
    branch: { category: 'AUTHORITATIVE TOOLS', title: 'Mock account APIs', detail: 'Order state and checked actions' },
    branchLabel: 'lookup / action', returnLabel: 'confirmed state',
    note: 'Policy text and account records have different authority. Blocked or uncertain actions go to a human.',
  },
}

function Box({ x, y, step }: { x: number; y: number; step: Step }) {
  return <g className={`planned-map-box planned-map-box-${step.tone ?? 'default'}`}>
    <rect x={x} y={y} width="166" height="86" rx="9" />
    <text x={x + 12} y={y + 22} className="planned-map-category">{step.category}</text>
    <text x={x + 12} y={y + 47} className="planned-map-title">{step.title}</text>
    <text x={x + 12} y={y + 69} className="planned-map-detail">{step.detail}</text>
  </g>
}

export default function PlannedSystemDiagram({ systemId }: { systemId: string }) {
  const design = designs[systemId]
  if (!design) return null
  return <div className="planned-system-diagram" role="region" aria-label={design.summary}>
    <svg viewBox="0 0 950 350" aria-hidden="true">
      <defs><marker id="planned-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" /></marker></defs>
      <g className="planned-map-edges" markerEnd="url(#planned-arrow)">
        <path d="M176 79 H196 M362 79 H382 M548 79 H568 M734 79 H754" />
        <path d="M422 122 V215 M508 215 V122" />
      </g>
      {design.main.map((step, index) => <Box key={step.title} x={10 + index * 186} y={36} step={step} />)}
      <Box x={382} y={220} step={design.branch} />
      <text x="389" y="176" className="planned-map-edge-label">{design.branchLabel} ↓</text>
      <text x="508" y="176" className="planned-map-edge-label">↑ {design.returnLabel}</text>
      <text x="14" y="328" className="planned-map-footnote">{design.note}</text>
    </svg>
  </div>
}
