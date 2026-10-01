import { useEffect, useMemo, useRef, useState } from 'react'

import { backfillCompany, getResearchRun, getResearchRuns, streamResearch } from './api'
import IncidentWorkspace from './IncidentWorkspace'
import KnowledgeAssistant from './KnowledgeAssistant'
import SupportAssistant from './SupportAssistant'
import ArchitectureModal from './ArchitectureModal'
import ResearchRunView from './ResearchRunView'
import { CitationTooltip, CitationTooltipProvider } from './components/CitationTooltip'
import { citationKeyword, sourceCount, visibleResearchLimitations } from './researchReportUi'
import { currentResearchRequest, researchSourceUse, researchTabFromUrl, withResearchRun } from './researchRunUi'
import type { ResearchTab } from './researchRunUi'
import type {
  BackfillRequest,
  BackfillResult,
  BriefingRequest,
  EvidenceItem,
  Finding,
  ResearchRunDetail,
  ResearchRunSummary,
  ResearchWorkflowResult,
  ResearchWorkflowStep,
} from './types'

type WorkspaceMode = 'user' | 'admin'

interface ToolDefinition {
  id: string
  number: string
  title: string
  shortTitle: string
  category: string
  description: string
  availability: 'ready' | 'planned'
  flow?: string[]
  input?: string
  output?: string
  boundary?: string
  firstSlice?: string
  sourcePath?: string
}

const TOOLS: ToolDefinition[] = [
  {
    id: 'incident-investigation',
    number: '01',
    title: 'Incident Investigation',
    shortTitle: 'Incidents',
    category: 'Operations',
    description: 'Replay service logs, classify incident candidates, and produce a cited report.',
    availability: 'ready',
    flow: ['Log stream', 'Group and classify', 'Scoped investigation', 'Cited report'],
    input: 'A synthetic multi-service log stream and a maximum of one to three reports per replay.',
    output: 'A timeline that separates facts, correlations, and hypotheses, with source locators and unknowns.',
    boundary: 'Query services narrow telemetry before the agent sees it; every material claim needs evidence.',
    firstSlice: 'One synthetic checkout incident, an inventory fallback nonincident, and a nearby misleading deployment.',
    sourcePath: 'backend/incident_investigation/',
  },
  {
    id: 'coding-agent',
    number: '02',
    title: 'Coding Agent',
    shortTitle: 'Coding',
    category: 'Developer tools',
    description: 'Search a fixture repo, edit in isolation, test, and propose a reviewable diff.',
    availability: 'planned',
    flow: ['Issue', 'Code search', 'Isolated edit + tests', 'Diff for review'],
    input: 'An issue against a small fixture repository with explicit allowed paths.',
    output: 'A unified diff, validation results, explanation, and risks for human review.',
    boundary: 'The runtime enforces file and execution permissions; tests provide deterministic feedback.',
    firstSlice: 'One regression fixture with a passing fix and a blocked out-of-scope edit.',
    sourcePath: 'backend/coding_agent/',
  },
  {
    id: 'knowledge-action',
    number: '03',
    title: 'Knowledge + Action',
    shortTitle: 'Knowledge',
    category: 'Internal assistant',
    description: 'Answer questions from authorized synthetic documents with checked citations.',
    availability: 'ready',
    flow: ['Ingest + index', 'Deterministic checks → Jev', 'ACL hybrid retrieval', 'Cited answer or approved task'],
    input: 'A synthetic employee question over documents, a policy, and a support ticket.',
    output: 'A cited answer, explicit abstention, or approved mock support task with a saved workflow.',
    boundary: 'Cheap deterministic checks precede Jev; ACL filtering precedes retrieval and proposal context; policy rechecks approval before idempotent execution.',
    firstSlice: 'Two simulated personas, one support task type, explicit approval, and a local idempotent executor.',
    sourcePath: 'backend/internal_knowledge_action/',
  },
  {
    id: 'customer-support',
    number: '04',
    title: 'Customer Support',
    shortTitle: 'Support',
    category: 'Customer operations',
    description: 'Combine policy answers and account tools with action checks and human escalation.',
    availability: 'ready',
    flow: ['Request checks + Jev', 'Scoped policy + orders', 'Verify answer or proposal', 'Confirm change / review case'],
    input: 'A simulated customer conversation with mock orders and policy records.',
    output: 'A policy-cited answer, a confirmed action state, or a reasoned human escalation.',
    boundary: 'Account state comes from APIs; policy and ownership checks govern every action.',
    firstSlice: 'One policy answer, one eligible cancellation, one blocked action, and one escalation.',
    sourcePath: 'backend/customer_support/',
  },
  {
    id: 'research',
    number: '05',
    title: 'Research & Workflow',
    shortTitle: 'Research',
    category: 'Research',
    description: 'Produce cited company research with deterministic evidence verification.',
    availability: 'ready',
  },
]

const RUN_POLL_INTERVAL_MS = 1_500
const RUN_STALE_AFTER_MS = 210_000

function delay(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds))
}

function workflowFromRun(run: ResearchRunDetail): ResearchWorkflowResult {
  return {
    run_id: run.run_id,
    status: run.status,
    briefing: run.briefing_payload,
    verification: run.verification_payload,
  }
}

function failureMessage(run: ResearchRunDetail) {
  const message = run.error_payload?.message
  return typeof message === 'string' ? message : 'Research workflow failed'
}

function runIsStale(run: ResearchRunDetail) {
  const startedAt = Date.parse(run.started_at ?? run.created_at)
  return Number.isFinite(startedAt) && Date.now() - startedAt > RUN_STALE_AFTER_MS
}

const LOGFIRE_PROJECT_URL =
  import.meta.env.VITE_LOGFIRE_PROJECT_URL ??
  'https://logfire-us.pydantic.dev/seijim27/ai-systems'

function toolFromLocation(): ToolDefinition | null {
  if (window.location.pathname === '/incident-investigation' || window.location.pathname.startsWith('/incident-investigation/')) {
    return TOOLS[0]
  }
  const toolId = new URLSearchParams(window.location.search).get('tool')
  return TOOLS.find((tool) => tool.id === toolId) ?? null
}

const DEFAULT_RESEARCH_REQUEST: BriefingRequest = {
  symbol: 'AAPL',
  as_of: new Date().toISOString(),
  research_question:
    "How have Apple's revenue and profits changed over the past two years, and do its latest filing risks or recent news change the 12-month outlook?",
  audience: 'investors',
  time_horizon: '12m',
}

const DEFAULT_BACKFILL_REQUEST: BackfillRequest = {
  symbol: 'AAPL',
  as_of: new Date().toISOString().slice(0, 10),
  include_8k: true,
}

function formatDate(value: string | null): string {
  if (!value) return 'Not available'
  return new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function buildLogfireUrl(traceId: string): string {
  const query = new URLSearchParams({
    q: `trace_id='${traceId}'`,
    last: '14d',
  })
  return `${LOGFIRE_PROJECT_URL}/?${query.toString()}`
}

function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase().replaceAll('_', '-')
  return <span className={`status-pill status-${normalized}`}>{status}</span>
}

function AppHeader({ onHome, selectedTool, onArchitecture }: { onHome: () => void; selectedTool: ToolDefinition | null; onArchitecture: () => void }) {
  return (
    <header className="app-header">
      <button className="brand-button" type="button" onClick={onHome}>
        <span className="brand-mark">AS</span>
        <span>
          <strong>AI Systems</strong>
          <small>Applied agent engineering</small>
        </span>
      </button>
      <div className="header-actions">
        <div className="header-meta"><span className="live-indicator" aria-hidden="true" />Local workspace</div>
        {selectedTool && <button className="architecture-entry" type="button" onClick={onArchitecture} aria-haspopup="dialog">
          <span aria-hidden="true">▦</span> System architecture
        </button>}
      </div>
    </header>
  )
}

function ToolRail({
  selectedId,
  onSelect,
}: {
  selectedId: string | null
  onSelect: (tool: ToolDefinition) => void
}) {
  return (
    <aside className="tool-rail">
      <div className="rail-heading">
        <span>Tools</span>
        <span>{TOOLS.length.toString().padStart(2, '0')}</span>
      </div>
      <nav className="tool-nav" aria-label="AI system tools">
        {TOOLS.map((tool) => (
          <button
            className={`tool-nav-item ${selectedId === tool.id ? 'active' : ''}`}
            key={tool.id}
            onClick={() => onSelect(tool)}
            type="button"
          >
            <span className="tool-nav-number">{tool.number}</span>
            <span className="tool-nav-copy">
              <strong>{tool.shortTitle}</strong>
              <small>{tool.category}</small>
            </span>
            <span
              className={`availability-dot ${tool.availability}`}
              title={tool.availability === 'ready' ? 'Available' : 'Planned'}
            />
          </button>
        ))}
      </nav>
      <div className="rail-footer">
        <span className="availability-dot ready" />
        4 runnable · 1 architecture scaffold
      </div>
    </aside>
  )
}

function ToolCatalog({ onSelect }: { onSelect: (tool: ToolDefinition) => void }) {
  return (
    <section className="catalog-view">
      <div className="catalog-intro">
        <p className="section-kicker">Workbench</p>
        <h1>Five AI system designs. Four runnable demos.</h1>
        <p>
          Compare the request flow, model boundary, and output of common interview systems.
          Investigate a synthetic incident, run cited company research, or ask an access-controlled knowledge assistant. Customer Support answers camera-shop questions and routes checked order changes or human-review cases. Coding Agent remains planned.
        </p>
      </div>

      <div className="catalog-grid">
        {TOOLS.map((tool) => (
          <button
            className={`catalog-item ${tool.availability}`}
            key={tool.id}
            onClick={() => onSelect(tool)}
            type="button"
          >
            <div className="catalog-item-topline">
              <span>{tool.number}</span>
              <StatusPill status={tool.availability === 'ready' ? 'Available' : 'Planned'} />
            </div>
            <h2>{tool.title}</h2>
            <p>{tool.description}</p>
            <span className="catalog-action">
              {tool.availability === 'ready' ? 'Open tool' : 'View scope'}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

function SystemScaffold({ tool }: { tool: ToolDefinition }) {
  return (
    <section className="scaffold-view">
      <div className="scaffold-heading">
        <span className="scaffold-number">{tool.number}</span>
      <StatusPill status={tool.availability === 'ready' ? 'Runnable demo' : 'Architecture scaffold'} />
      </div>
      <p className="section-kicker">{tool.category}</p>
      <h1>{tool.title}</h1>
      <p className="scaffold-description">{tool.description}</p>

      <div className="scaffold-flow" aria-label={tool.id === 'knowledge-action' ? 'Implemented knowledge and action request flow' : 'Intended request flow'}>
        {tool.flow?.map((step, index) => (
          <div className="scaffold-flow-step" key={step}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <strong>{step}</strong>
          </div>
        ))}
      </div>

      <div className="scaffold-grid">
        <div><span>Input</span><p>{tool.input}</p></div>
        <div><span>Output</span><p>{tool.output}</p></div>
        <div><span>Key boundary</span><p>{tool.boundary}</p></div>
        <div><span>First runnable slice</span><p>{tool.firstSlice}</p></div>
      </div>
      {tool.id === 'knowledge-action' && <KnowledgeAssistant />}
      {tool.id === 'customer-support' && <SupportAssistant />}
      <p className="scaffold-note">
        {tool.id === 'knowledge-action'
          ? 'Ingestion, retrieval, cited answers, and approval-gated mock support tasks run. Demo personas and approvers are simulated; task records stay local.'
          : tool.id === 'customer-support' ? 'Synthetic orders, confirmed mock changes, and saved human-review cases run. No payments or external tickets are created.' : 'Architecture and proposed contracts only. No agent or API is connected yet.'}
        {' '}See <code>{tool.sourcePath}README.md</code> in the repository.
      </p>
    </section>
  )
}

function ResearchForm({
  request,
  loading,
  onChange,
  onSubmit,
}: {
  request: BriefingRequest
  loading: boolean
  onChange: (request: BriefingRequest) => void
  onSubmit: () => void
}) {
  const setField = <Key extends keyof BriefingRequest>(
    key: Key,
    value: BriefingRequest[Key],
  ) => onChange({ ...request, [key]: value })

  return (
    <form
      className="research-form"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <div className="form-row form-row-primary">
        <label>
          <span>Symbol</span>
          <input
            maxLength={10}
            value={request.symbol}
            onChange={(event) => setField('symbol', event.target.value.toUpperCase())}
          />
        </label>
        <label>
          <span>Audience</span>
          <select
            value={request.audience}
            onChange={(event) => setField('audience', event.target.value)}
          >
            <option value="investors">Investors</option>
            <option value="executives">Executives</option>
            <option value="analysts">Analysts</option>
          </select>
        </label>
        <label>
          <span>Horizon</span>
          <select
            value={request.time_horizon}
            onChange={(event) => setField('time_horizon', event.target.value)}
          >
            <option value="7d">7 days</option>
            <option value="3m">3 months</option>
            <option value="12m">12 months</option>
            <option value="3y">3 years</option>
          </select>
        </label>
      </div>
      <label className="question-field">
        <span>Research question</span>
        <textarea
          rows={4}
          value={request.research_question}
          onChange={(event) => setField('research_question', event.target.value)}
        />
        <small>Be specific about the decision, risk, or time horizon you care about.</small>
      </label>
      <button
        className="primary-button"
        disabled={loading || request.research_question.trim().length < 30}
        type="submit"
      >
        {loading ? 'Researching…' : 'Run research'}
      </button>
    </form>
  )
}

function CitationChip({ evidence }: { evidence: EvidenceItem }) {
  const isVersionTwo = 'evidence_id' in evidence
  const content = isVersionTwo
    ? evidence.evidence_type === 'document'
      ? evidence.quote
      : evidence.value
    : evidence.content
  const sourceLabel = isVersionTwo
    ? evidence.title
    : evidence.title || evidence.source
  const metadata = [
    ...('period_end' in evidence && evidence.period_end
      ? [{ label: 'Period ended', value: formatDate(evidence.period_end) }]
      : []),
    ...(evidence.published_at
      ? [{ label: 'Published', value: formatDate(evidence.published_at) }]
      : []),
    ...('field_path' in evidence && evidence.field_path
      ? [{ value: evidence.field_path, code: true }]
      : []),
    ...('chunk_id' in evidence && evidence.chunk_id
      ? [{ label: 'Chunk', value: evidence.chunk_id, code: true }]
      : []),
    { value: evidence.reference_id, code: true },
    ...(evidence.url ? [{ value: 'Open source ↗', href: evidence.url }] : []),
  ]
  return <CitationTooltip label={citationKeyword(evidence)} sourceTitle={sourceLabel} excerpt={typeof content === 'number' ? content.toLocaleString('en-US') : String(content)} metadata={metadata} />
}

function confidenceLabel(confidence: number): string {
  if (confidence >= 3) return 'High confidence'
  if (confidence >= 2) return 'Moderate confidence'
  return 'Low confidence'
}

function FindingCard({
  finding,
  index,
  isSupported,
}: {
  finding: Finding
  index: number
  isSupported: boolean
}) {
  return (
    <article className={`finding-card ${isSupported ? '' : 'finding-unsupported'}`}>
      <div className="finding-index">{String(index + 1).padStart(2, '0')}</div>
      <div className="finding-content">
        <div className="finding-tags">
          <span>{finding.claim_type}</span>
          <span>{confidenceLabel(finding.confidence)}</span>
          <span>{sourceCount(finding.evidence)} source{sourceCount(finding.evidence) === 1 ? '' : 's'}</span>
          {finding.evidence.map((evidence, evidenceIndex) => (
            <CitationChip
              evidence={evidence}
              key={'evidence_id' in evidence ? evidence.evidence_id : `${evidence.reference_id}-${evidence.chunk_id ?? evidence.field_path ?? evidenceIndex}`}
            />
          ))}
          {!isSupported && <span className="finding-warning">Needs review</span>}
        </div>
        <h3>{finding.statement}</h3>
      </div>
    </article>
  )
}

function BriefingView({
  result,
  symbol,
  asOf,
  timeHorizon,
  steps,
}: {
  result: ResearchWorkflowResult
  symbol: string
  asOf: string
  timeHorizon: string
  steps: ResearchWorkflowStep[]
}) {
  if (!result.briefing) {
    return (
      <div className="empty-state">
        <strong>Run accepted</strong>
        <p>The workflow is currently {result.status}. Open the Run tab for progress.</p>
      </div>
    )
  }

  const approvalReady = result.verification?.approval_ready ?? false
  const unsupportedFindings = new Set(
    result.verification?.unsupported_finding_indexes ?? [],
  )
  const evidenceCount = result.briefing.key_findings.reduce(
    (total, finding) => total + finding.evidence.length,
    0,
  )
  const sourceUse = researchSourceUse(steps, result.briefing)
  const limitations = visibleResearchLimitations(result.briefing.limitations)

  return (
    <div className="briefing-view">
      <article className="research-note">
        <header className="note-masthead">
          <div className="note-title">
            <span>Company research</span>
            <h2>{symbol.toUpperCase()}</h2>
          </div>
          <dl className="note-metadata">
            <div>
              <dt>As of</dt>
              <dd>{formatDate(asOf)}</dd>
            </div>
            <div>
              <dt>Horizon</dt>
              <dd>{timeHorizon}</dd>
            </div>
            <div>
              <dt>Evidence</dt>
              <dd>{evidenceCount} references</dd>
            </div>
            <div>
              <dt>Automated checks</dt>
              <dd className={approvalReady ? 'verified' : 'review-required'}>
                <span aria-hidden="true" />
                {approvalReady ? 'Passed' : 'Needs review'}
              </dd>
            </div>
          </dl>
        </header>

        {sourceUse.tavilySearches > 0 && (
          <section className="research-source-use" aria-label="Tavily source use">
            <strong>Tavily source use</strong>
            <p>
              {sourceUse.tavilySearches} search{sourceUse.tavilySearches === 1 ? '' : 'es'} ·{' '}
              {sourceUse.inspectedCandidates} citable passage{sourceUse.inspectedCandidates === 1 ? '' : 's'} inspected ·{' '}
              {sourceUse.citedTavilyEvidence} cited in the final findings.
            </p>
            {sourceUse.citedTavilyEvidence === 0 && <p>No Tavily passage supports a final finding. See the Run tab for the search, extraction, and source decisions.</p>}
            {sourceUse.citedTavilyEvidence > 0 && <p className="source-context-note">Web publication dates are provider estimates. Cited page text reflects what was retrieved for this run.</p>}
            {sourceUse.dispositions.length > 0 && (
              <details>
                <summary>Source decisions</summary>
                <ul>
                  {sourceUse.dispositions.map((decision) => (
                    <li key={decision.evidence_id}><strong>{decision.outcome}</strong> · {decision.url ? <a href={decision.url} target="_blank" rel="noreferrer">{decision.title || decision.evidence_id}</a> : decision.title || decision.evidence_id}: {decision.reason}</li>
                  ))}
                </ul>
              </details>
            )}
          </section>
        )}

        <section className="briefing-summary">
          <h2>Investment summary</h2>
          <p>{result.briefing.executive_summary}</p>
        </section>

        <section className="findings-section">
          <div className="section-heading-row">
            <div>
              <h2>Key findings</h2>
              <p>Ranked claims and the evidence used to support them.</p>
            </div>
            <span>{result.briefing.key_findings.length}</span>
          </div>
          <div className="findings-list">
            {result.briefing.key_findings.map((finding, index) => (
              <FindingCard
                finding={finding}
                index={index}
                isSupported={!unsupportedFindings.has(index)}
                key={`${index}-${finding.statement}`}
              />
            ))}
          </div>
        </section>

        <section className="outlook-section">
          <h2>Outlook</h2>
          <p>{result.briefing.outlook}</p>
        </section>

        {limitations.length > 0 && (
          <section className="limitations-section">
            <h2>Research limitations</h2>
            <ul>
              {limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </section>
        )}

        <footer className="note-footer">
          <span>
            Generated research · Review cited evidence · Web discovery via{' '}
            <a href="https://tavily.com/" rel="noreferrer" target="_blank">
              Tavily
            </a>
          </span>
        </footer>
      </article>
    </div>
  )
}

function BackfillPanel() {
  const [request, setRequest] = useState<BackfillRequest>(DEFAULT_BACKFILL_REQUEST)
  const [result, setResult] = useState<BackfillResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setLoading(true)
    setError(null)
    try {
      setResult(await backfillCompany(request))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Backfill failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="admin-panel backfill-panel">
      <div className="panel-heading">
        <div>
          <h2>Filing setup</h2>
          <p>Load SEC filings for document search. The agent discovers current news during a run.</p>
        </div>
        {result && <StatusPill status={result.status} />}
      </div>
      <div className="compact-form-grid">
        <label>
          <span>Symbol</span>
          <input
            value={request.symbol}
            onChange={(event) => setRequest({ ...request, symbol: event.target.value.toUpperCase() })}
          />
        </label>
        <label>
          <span>As of</span>
          <input
            type="date"
            value={request.as_of}
            onChange={(event) => setRequest({ ...request, as_of: event.target.value })}
          />
        </label>
      </div>
      <div className="checkbox-row">
        <label>
          <input
            checked={request.include_8k}
            onChange={(event) => setRequest({ ...request, include_8k: event.target.checked })}
            type="checkbox"
          />
          Include 8-K filings
        </label>
      </div>
      {error && <div className="inline-error">{error}</div>}
      <button className="secondary-button" disabled={loading} onClick={submit} type="button">
        {loading ? 'Loading filings…' : 'Load filings'}
      </button>
      {result && (
        <div className="backfill-result">
          <strong>{result.total_documents_processed} documents processed</strong>
          <span>{result.failures} source failures</span>
        </div>
      )}
    </section>
  )
}

function AdminView({
  workflow,
  run,
}: {
  workflow: ResearchWorkflowResult | null
  run: ResearchRunDetail | null
}) {
  const verification = run?.verification_payload ?? workflow?.verification ?? null
  const rawPayload = run ?? workflow

  return (
    <div className="admin-view">
      <BackfillPanel />

      <section className="admin-panel">
        <div className="panel-heading">
          <div>
            <h2>Run diagnostics</h2>
            <p>Persistence, verification, checkpoint, and telemetry state.</p>
          </div>
          {run && <StatusPill status={run.status} />}
        </div>
        {!run ? (
          <div className="admin-empty">Run a research request to populate diagnostics.</div>
        ) : (
          <>
            <div className="diagnostic-grid">
              <div>
                <span>Checkpoint</span>
                <strong>{run.checkpoint_stage ?? 'None'}</strong>
              </div>
              <div>
                <span>Model</span>
                <strong>{run.model_name}</strong>
              </div>
              <div>
                <span>Completed</span>
                <strong>{formatDate(run.completed_at)}</strong>
              </div>
            </div>
            {run.trace_id && (
              <a className="trace-link" href={buildLogfireUrl(run.trace_id)} rel="noreferrer" target="_blank">
                Open complete Logfire trace
              </a>
            )}
          </>
        )}
      </section>

      <section className="admin-panel verification-panel">
        <div className="panel-heading">
          <div>
            <h2>Verification</h2>
            <p>What survived deterministic evidence checks and semantic grounding.</p>
          </div>
          {verification && (
            <StatusPill status={verification.approval_ready ? 'Approval ready' : 'Review required'} />
          )}
        </div>
        {!verification ? (
          <div className="admin-empty">No verification output yet.</div>
        ) : (
          <div className="verification-grid">
            <div>
              <strong>{verification.unsupported_finding_indexes.length}</strong>
              <span>Unsupported findings</span>
              <code>{verification.unsupported_finding_indexes.join(', ') || 'None'}</code>
            </div>
            <div>
              <strong>{verification.invalid_evidence_references.length}</strong>
              <span>Invalid references</span>
              <div className="reference-list">
                {verification.invalid_evidence_references.slice(0, 8).map((reference, index) => (
                  <code key={`${reference}-${index}`}>{reference}</code>
                ))}
              </div>
            </div>
            <div>
              <strong>{verification.grounding_failures.length}</strong>
              <span>Grounding failures</span>
              <div className="reference-list">
                {verification.grounding_failures.map((failure) => (
                  <p key={`${failure.finding_index}-${failure.reason}`}>
                    Finding {failure.finding_index + 1}: {failure.reason}
                  </p>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="admin-panel raw-panel">
        <details>
          <summary>Raw structured payload</summary>
          <pre>{rawPayload ? JSON.stringify(rawPayload, null, 2) : 'No run data.'}</pre>
        </details>
      </section>
    </div>
  )
}

function RunHistory({
  runs,
  selectedRunId,
  loading,
  error,
  onSelect,
  onNew,
}: {
  runs: ResearchRunSummary[]
  selectedRunId: string | null
  loading: boolean
  error: string | null
  onSelect: (runId: string) => void
  onNew: () => void
}) {
  return (
    <aside className="run-history">
      <div className="run-history-heading">
        <div>
          <h2>Recent research</h2>
          <span>{runs.length} saved runs</span>
        </div>
        <button onClick={onNew} type="button">New</button>
      </div>
      {error && runs.length === 0 ? (
        <div className="history-message">Could not load saved runs: {error}</div>
      ) : loading && runs.length === 0 ? (
        <div className="history-message">Loading saved research…</div>
      ) : runs.length === 0 ? (
        <div className="history-message">Completed and failed runs will appear here.</div>
      ) : (
        <div className="run-history-list">
          {runs.map((run) => (
            <button
              className={`run-history-item ${selectedRunId === run.run_id ? 'active' : ''}`}
              key={run.run_id}
              onClick={() => onSelect(run.run_id)}
              type="button"
            >
              <span className="history-item-topline">
                <strong>{run.symbol}</strong>
                <StatusPill status={run.status} />
              </span>
              <span className="history-question">{run.research_question}</span>
              <span className="history-date">{formatDate(run.created_at)}</span>
            </button>
          ))}
        </div>
      )}
    </aside>
  )
}

function ResearchWorkspace() {
  const [mode, setMode] = useState<WorkspaceMode>('user')
  const [activeTab, setActiveTab] = useState<ResearchTab>(() => researchTabFromUrl(new URL(window.location.href)))
  const [request, setRequest] = useState<BriefingRequest>(DEFAULT_RESEARCH_REQUEST)
  const [workflow, setWorkflow] = useState<ResearchWorkflowResult | null>(null)
  const [runDetail, setRunDetail] = useState<ResearchRunDetail | null>(null)
  const [liveSteps, setLiveSteps] = useState<ResearchWorkflowStep[]>([])
  const [currentRunId, setCurrentRunId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('run'))
  const [runHistory, setRunHistory] = useState<ResearchRunSummary[]>([])
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const selectionRequest = useRef(0)

  const updateRunUrl = (runId: string | null, tab: ResearchTab, replace = false) => {
    const url = withResearchRun(new URL(window.location.href), runId, tab)
    window.history[replace ? 'replaceState' : 'pushState']({}, '', url)
  }

  const selectTab = (tab: ResearchTab) => {
    setActiveTab(tab)
    updateRunUrl(currentRunId, tab)
  }

  const applyRunDetail = (savedRun: ResearchRunDetail) => {
    setRunDetail(savedRun)
    setWorkflow(workflowFromRun(savedRun))
    setCurrentRunId(savedRun.run_id)
  }

  const pollRunUntilFinished = async (
    runId: string,
    initialRun?: ResearchRunDetail,
    requestId = selectionRequest.current,
  ) => {
    let savedRun = initialRun ?? (await getResearchRun(runId))
    if (requestId !== selectionRequest.current) throw new Error('Research selection changed')

    while (savedRun.status === 'pending' || savedRun.status === 'running') {
      applyRunDetail(savedRun)
      if (runIsStale(savedRun)) {
        throw new Error(
          'This research run stopped updating and appears stale. Start a new request or retry after the stale run is cleared.',
        )
      }
      await delay(RUN_POLL_INTERVAL_MS)
      savedRun = await getResearchRun(runId)
      if (requestId !== selectionRequest.current) throw new Error('Research selection changed')
    }

    applyRunDetail(savedRun)
    if (savedRun.status === 'failed') {
      throw new Error(failureMessage(savedRun))
    }
    return savedRun
  }

  const showSavedRun = async (runId: string) => {
    const requestId = ++selectionRequest.current
    setHistoryLoading(true)
    setError(null)
    setLiveSteps([])
    setCurrentRunId(runId)
    try {
      const savedRun = await getResearchRun(runId)
      if (requestId !== selectionRequest.current) return
      applyRunDetail(savedRun)
      setRequest(savedRun.request_payload)
      if (savedRun.status === 'pending' || savedRun.status === 'running') {
        setActiveTab('run')
        setLoading(true)
        await pollRunUntilFinished(runId, savedRun)
        if (requestId !== selectionRequest.current) return
        await refreshHistory()
      }
    } catch (caught) {
      if (requestId !== selectionRequest.current) return
      setError(caught instanceof Error ? caught.message : 'Could not load this run')
    } finally {
      if (requestId === selectionRequest.current) {
        setLoading(false)
        setHistoryLoading(false)
      }
    }
  }

  const refreshHistory = async () => {
    try {
      setRunHistory(await getResearchRuns())
      setHistoryError(null)
    } catch (caught) {
      setHistoryError(caught instanceof Error ? caught.message : 'Could not load run history')
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    void refreshHistory()
    const initialRunId = new URLSearchParams(window.location.search).get('run')
    if (initialRunId) void showSavedRun(initialRunId)

    const handleNavigation = () => {
      const runId = new URLSearchParams(window.location.search).get('run')
      setActiveTab(researchTabFromUrl(new URL(window.location.href)))
      if (runId) void showSavedRun(runId)
      else {
        ++selectionRequest.current
        setWorkflow(null)
        setRunDetail(null)
        setLiveSteps([])
        setCurrentRunId(null)
      }
    }
    window.addEventListener('popstate', handleNavigation)
    return () => window.removeEventListener('popstate', handleNavigation)
  }, [])

  const run = async () => {
    const requestId = ++selectionRequest.current
    let streamRunId: string | null = null
    setLoading(true)
    setError(null)
    setWorkflow(null)
    setRunDetail(null)
    setLiveSteps([])
    setCurrentRunId(null)
    setActiveTab('run')
    updateRunUrl(null, 'run')
    try {
      const normalizedRequest = currentResearchRequest(request)
      setRequest(normalizedRequest)
      const nextWorkflow = await streamResearch(normalizedRequest, (step) => {
        if (requestId !== selectionRequest.current) return
        if (!streamRunId) {
          streamRunId = step.run_id
          setCurrentRunId(step.run_id)
          updateRunUrl(step.run_id, 'run', true)
        }
        if (streamRunId === step.run_id) setLiveSteps((previous) => [...previous, step])
      })
      if (requestId !== selectionRequest.current) return
      if (streamRunId && nextWorkflow.run_id !== streamRunId) throw new Error('The backend returned a different research run ID.')
      streamRunId = nextWorkflow.run_id
      setWorkflow(nextWorkflow)
      setCurrentRunId(nextWorkflow.run_id)
      updateRunUrl(nextWorkflow.run_id, nextWorkflow.status === 'completed' ? 'briefing' : 'run', true)
      await pollRunUntilFinished(nextWorkflow.run_id)
      if (requestId !== selectionRequest.current) return
      setActiveTab('briefing')
      await refreshHistory()
    } catch (caught) {
      if (requestId !== selectionRequest.current) return
      if (streamRunId) {
        try {
          await pollRunUntilFinished(streamRunId)
          if (requestId !== selectionRequest.current) return
          setActiveTab('briefing')
          updateRunUrl(streamRunId, 'briefing', true)
          await refreshHistory()
          return
        } catch (recoveryError) {
          if (requestId !== selectionRequest.current) return
          setError(recoveryError instanceof Error ? recoveryError.message : 'Research workflow failed')
        }
      } else {
        setError(caught instanceof Error ? caught.message : 'Research workflow failed')
      }
      setActiveTab('run')
    } finally {
      if (requestId === selectionRequest.current) setLoading(false)
    }
  }

  const runStatus = runDetail?.status ?? workflow?.status
  const headingMeta = useMemo(
    () => (runStatus ? `${request.symbol.toUpperCase()} · ${runStatus}` : 'Ready for a new run'),
    [request.symbol, runStatus],
  )

  const selectSavedRun = (runId: string) => {
    const tab: ResearchTab = runHistory.find((saved) => saved.run_id === runId)?.status === 'completed' ? 'briefing' : 'run'
    setActiveTab(tab)
    updateRunUrl(runId, tab)
    void showSavedRun(runId)
  }

  const startNewResearch = () => {
    ++selectionRequest.current
    updateRunUrl(null, 'run')
    setWorkflow(null)
    setRunDetail(null)
    setLiveSteps([])
    setCurrentRunId(null)
    setActiveTab('run')
    setError(null)
    setLoading(false)
    setRequest({ ...DEFAULT_RESEARCH_REQUEST, as_of: new Date().toISOString() })
  }

  return (
    <section className="workspace-view">
      <div className="workspace-heading">
        <div>
          <div className="workspace-title-row">
            <span className="tool-number-large">05</span>
            <div>
              <h1>Research Briefing</h1>
              <p>{headingMeta}</p>
            </div>
          </div>
        </div>
        <div className="mode-switch" aria-label="Research workspace mode">
          <button className={mode === 'user' ? 'active' : ''} onClick={() => setMode('user')} type="button">
            Research
          </button>
          <button className={mode === 'admin' ? 'active' : ''} onClick={() => setMode('admin')} type="button">
            Admin
          </button>
        </div>
      </div>

      <div className="research-workspace-grid">
        <div className="research-main-column">
          <ResearchForm request={request} loading={loading} onChange={setRequest} onSubmit={run} />

          {error && (
            <div className="workflow-error">
              <strong>Research failed</strong>
              <span>{error}</span>
            </div>
          )}

          {mode === 'user' && <>
            <div className="research-tabs" role="tablist" aria-label="Research views">
              <button type="button" role="tab" aria-selected={activeTab === 'run'} onClick={() => selectTab('run')}>Run <small>Workflow steps and decisions</small></button>
              <button type="button" role="tab" aria-selected={activeTab === 'briefing'} disabled={!workflow?.briefing} onClick={() => selectTab('briefing')}>Briefing <small>Cited findings and limits</small></button>
            </div>
            <section role="tabpanel" aria-label="Research run" hidden={activeTab !== 'run'}>
              <ResearchRunView steps={runDetail?.workflow_steps ?? liveSteps} runId={currentRunId} resumedFrom={runDetail?.resumed_from_run_id ?? null} loading={loading} status={runDetail?.status ?? workflow?.status ?? null} error={error} />
            </section>
            <section role="tabpanel" aria-label="Research briefing" hidden={activeTab !== 'briefing'}>
              {workflow?.briefing && <BriefingView result={workflow} symbol={runDetail?.symbol ?? request.symbol} asOf={runDetail?.as_of ?? request.as_of} timeHorizon={request.time_horizon} steps={runDetail?.workflow_steps ?? liveSteps} />}
            </section>
          </>}
          {!loading && mode === 'admin' && <AdminView workflow={workflow} run={runDetail} />}
        </div>
        <RunHistory
          runs={runHistory}
          selectedRunId={currentRunId}
          loading={historyLoading}
          error={historyError}
          onSelect={selectSavedRun}
          onNew={startNewResearch}
        />
      </div>
    </section>
  )
}

export default function App() {
  const [selectedTool, setSelectedTool] = useState<ToolDefinition | null>(toolFromLocation)
  const [architectureOpen, setArchitectureOpen] = useState(false)

  useEffect(() => {
    const handleNavigation = () => { setSelectedTool(toolFromLocation()); setArchitectureOpen(false) }
    window.addEventListener('popstate', handleNavigation)
    return () => window.removeEventListener('popstate', handleNavigation)
  }, [])

  const navigateToTool = (tool: ToolDefinition | null) => {
    const url = new URL(window.location.href)
    url.pathname = tool?.id === 'incident-investigation' ? '/incident-investigation' : '/'
    if (tool && tool.id !== 'incident-investigation') url.searchParams.set('tool', tool.id)
    else url.searchParams.delete('tool')
    if (!tool || tool.id !== selectedTool?.id) url.searchParams.delete('run')
    if (tool?.id === 'incident-investigation') url.searchParams.set('tab', 'run')
    else url.searchParams.delete('tab')
    window.history.pushState({}, '', url)
    setSelectedTool(tool)
    setArchitectureOpen(false)
  }

  return (
    <CitationTooltipProvider>
      <div className="app-shell">
        <AppHeader onHome={() => navigateToTool(null)} selectedTool={selectedTool} onArchitecture={() => setArchitectureOpen(true)} />
        {selectedTool && architectureOpen && <ArchitectureModal systemId={selectedTool.id} title={selectedTool.title} availability={selectedTool.availability} onClose={() => setArchitectureOpen(false)} />}
        <div className="app-frame">
          <ToolRail selectedId={selectedTool?.id ?? null} onSelect={navigateToTool} />
          <main className="workspace-canvas">
            {!selectedTool && <ToolCatalog onSelect={navigateToTool} />}
            {selectedTool?.id === 'incident-investigation' && <IncidentWorkspace />}
            {selectedTool?.id === 'research' && <ResearchWorkspace />}
            {(selectedTool?.availability === 'planned' || selectedTool?.id === 'knowledge-action' || selectedTool?.id === 'customer-support') && <SystemScaffold tool={selectedTool} />}
          </main>
        </div>
      </div>
    </CitationTooltipProvider>
  )
}
