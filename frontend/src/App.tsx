import { useEffect, useMemo, useState } from 'react'

import { backfillCompany, getResearchRun, getResearchRuns, runResearch } from './api'
import IncidentWorkspace from './IncidentWorkspace'
import type {
  BackfillRequest,
  BackfillResult,
  BriefingRequest,
  EvidenceItem,
  Finding,
  ResearchRunDetail,
  ResearchRunSummary,
  ResearchWorkflowResult,
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
    description: 'Answer across permitted sources and route proposed actions through approval.',
    availability: 'planned',
    flow: ['User identity', 'ACL-aware retrieval', 'Cited answer', 'Action approval'],
    input: 'A synthetic employee question over mock documents and tickets, optionally requesting an action.',
    output: 'A cited answer and, when appropriate, an action proposal with an explicit approval state.',
    boundary: 'Access filtering happens before retrieval; a model cannot grant itself action permission.',
    firstSlice: 'Two users with different document access and one task-creation action that waits for approval.',
    sourcePath: 'backend/internal_knowledge_action/',
  },
  {
    id: 'customer-support',
    number: '04',
    title: 'Customer Support',
    shortTitle: 'Support',
    category: 'Customer operations',
    description: 'Combine policy answers and account tools with action checks and human escalation.',
    availability: 'planned',
    flow: ['Customer message', 'Policy + account lookup', 'Policy gate', 'Answer or handoff'],
    input: 'An authenticated synthetic customer conversation with mock orders and policy records.',
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

function localDateTimeValue(): string {
  const date = new Date(Date.now() - 60_000)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function localDateTimeFromIso(value: string): string {
  const date = new Date(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

const DEFAULT_RESEARCH_REQUEST: BriefingRequest = {
  symbol: 'AAPL',
  as_of: localDateTimeValue(),
  research_question:
    "What are Apple's primary business risks, and which are most consequential for investors over the next 12 months?",
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

function AppHeader({ onHome }: { onHome: () => void }) {
  return (
    <header className="app-header">
      <button className="brand-button" type="button" onClick={onHome}>
        <span className="brand-mark">AS</span>
        <span>
          <strong>AI Systems</strong>
          <small>Applied agent engineering</small>
        </span>
      </button>
      <div className="header-meta">
        <span className="live-indicator" aria-hidden="true" />
        Local workspace
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
        2 runnable · 3 architecture scaffolds
      </div>
    </aside>
  )
}

function ToolCatalog({ onSelect }: { onSelect: (tool: ToolDefinition) => void }) {
  return (
    <section className="catalog-view">
      <div className="catalog-intro">
        <p className="section-kicker">Workbench</p>
        <h1>Five AI system designs. Two runnable demos.</h1>
        <p>
          Compare the request flow, model boundary, and output of common interview systems.
          Investigate a synthetic incident or run cited company research. Three other systems remain architecture scaffolds.
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
        <StatusPill status="Architecture scaffold" />
      </div>
      <p className="section-kicker">{tool.category}</p>
      <h1>{tool.title}</h1>
      <p className="scaffold-description">{tool.description}</p>

      <div className="scaffold-flow" aria-label="Intended request flow">
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
      <p className="scaffold-note">
        Architecture and proposed contracts only. No agent or API is connected yet.
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
          <span>As of</span>
          <input
            type="datetime-local"
            value={request.as_of}
            onChange={(event) => setField('as_of', event.target.value)}
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

function LoadingBriefing() {
  return (
    <div className="briefing-loading" aria-live="polite">
      <div className="loading-heading">
        <span className="loading-pulse" />
        The workflow is researching, retrieving, and validating evidence.
      </div>
      <div className="skeleton skeleton-wide" />
      <div className="skeleton" />
      <div className="skeleton skeleton-short" />
      <div className="skeleton-card" />
      <div className="skeleton-card" />
    </div>
  )
}

function EvidenceDisclosure({ evidence }: { evidence: EvidenceItem }) {
  const isVersionTwo = 'evidence_id' in evidence
  const content = isVersionTwo
    ? evidence.evidence_type === 'document'
      ? evidence.quote
      : evidence.value
    : evidence.content
  const sourceLabel = isVersionTwo
    ? evidence.title
    : evidence.title || evidence.source
  const chunkId =
    evidence.evidence_type === 'document' && 'chunk_id' in evidence
      ? evidence.chunk_id
      : null
  const fieldPath =
    evidence.evidence_type === 'financial' && 'field_path' in evidence
      ? evidence.field_path
      : null

  return (
    <details className="evidence-item">
      <summary>
        <span>
          <strong>{sourceLabel}</strong>
          <small>
            {isVersionTwo && evidence.evidence_type === 'document'
              ? `${evidence.document_type} · ${evidence.content_quality}`
              : evidence.evidence_type}{' '}
            · {evidence.reference_id}
          </small>
        </span>
        <span className="disclosure-label">Evidence</span>
      </summary>
      <blockquote>{String(content)}</blockquote>
      <div className="evidence-meta">
        {evidence.published_at && <span>Published {formatDate(evidence.published_at)}</span>}
        {chunkId && <code>chunk {chunkId}</code>}
        {fieldPath && <code>{fieldPath}</code>}
        {'period_end' in evidence && evidence.period_end && (
          <span>Period ended {formatDate(evidence.period_end)}</span>
        )}
        {evidence.url && (
          <a href={evidence.url} rel="noreferrer" target="_blank">
            Open source
          </a>
        )}
      </div>
    </details>
  )
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
          <span>{finding.evidence.length} sources</span>
          {!isSupported && <span className="finding-warning">Needs review</span>}
        </div>
        <h3>{finding.statement}</h3>
        <div className="evidence-list">
          {finding.evidence.map((evidence, evidenceIndex) => (
            <EvidenceDisclosure
              evidence={evidence}
              key={
                'evidence_id' in evidence
                  ? evidence.evidence_id
                  : `${evidence.reference_id}-${evidence.chunk_id ?? evidence.field_path ?? evidenceIndex}`
              }
            />
          ))}
        </div>
      </div>
    </article>
  )
}

function BriefingView({
  result,
  symbol,
  asOf,
  timeHorizon,
}: {
  result: ResearchWorkflowResult
  symbol: string
  asOf: string
  timeHorizon: string
}) {
  if (!result.briefing) {
    return (
      <div className="empty-state">
        <strong>Run accepted</strong>
        <p>The workflow is currently {result.status}. Run ID: {result.run_id}</p>
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
              <dt>Review status</dt>
              <dd className={approvalReady ? 'verified' : 'review-required'}>
                <span aria-hidden="true" />
                {approvalReady ? 'Verified' : 'Review required'}
              </dd>
            </div>
          </dl>
        </header>

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

        {result.briefing.limitations.length > 0 && (
          <section className="limitations-section">
            <h2>Research limitations</h2>
            <ul>
              {result.briefing.limitations.map((limitation) => (
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
          <code>{result.run_id}</code>
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
                <span>Run ID</span>
                <code>{run.run_id}</code>
              </div>
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
  onSelect,
  onNew,
}: {
  runs: ResearchRunSummary[]
  selectedRunId: string | null
  loading: boolean
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
      {loading && runs.length === 0 ? (
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
  const [request, setRequest] = useState<BriefingRequest>(DEFAULT_RESEARCH_REQUEST)
  const [workflow, setWorkflow] = useState<ResearchWorkflowResult | null>(null)
  const [runDetail, setRunDetail] = useState<ResearchRunDetail | null>(null)
  const [runHistory, setRunHistory] = useState<ResearchRunSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const updateRunUrl = (runId: string | null) => {
    const url = new URL(window.location.href)
    if (runId) url.searchParams.set('run', runId)
    else url.searchParams.delete('run')
    window.history.pushState({}, '', url)
  }

  const applyRunDetail = (savedRun: ResearchRunDetail) => {
    setRunDetail(savedRun)
    setWorkflow(workflowFromRun(savedRun))
  }

  const pollRunUntilFinished = async (
    runId: string,
    initialRun?: ResearchRunDetail,
  ) => {
    let savedRun = initialRun ?? (await getResearchRun(runId))

    while (savedRun.status === 'pending' || savedRun.status === 'running') {
      applyRunDetail(savedRun)
      if (runIsStale(savedRun)) {
        throw new Error(
          'This research run stopped updating and appears stale. Start a new request or retry after the stale run is cleared.',
        )
      }
      await delay(RUN_POLL_INTERVAL_MS)
      savedRun = await getResearchRun(runId)
    }

    applyRunDetail(savedRun)
    if (savedRun.status === 'failed') {
      throw new Error(failureMessage(savedRun))
    }
    return savedRun
  }

  const showSavedRun = async (runId: string) => {
    setHistoryLoading(true)
    setError(null)
    try {
      const savedRun = await getResearchRun(runId)
      applyRunDetail(savedRun)
      setRequest({
        ...savedRun.request_payload,
        as_of: localDateTimeFromIso(savedRun.request_payload.as_of),
      })
      if (savedRun.status === 'pending' || savedRun.status === 'running') {
        setLoading(true)
        await pollRunUntilFinished(runId, savedRun)
        await refreshHistory()
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load this run')
    } finally {
      setLoading(false)
      setHistoryLoading(false)
    }
  }

  const refreshHistory = async () => {
    try {
      setRunHistory(await getResearchRuns())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load run history')
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
      if (runId) void showSavedRun(runId)
      else {
        setWorkflow(null)
        setRunDetail(null)
      }
    }
    window.addEventListener('popstate', handleNavigation)
    return () => window.removeEventListener('popstate', handleNavigation)
  }, [])

  const run = async () => {
    setLoading(true)
    setError(null)
    setWorkflow(null)
    setRunDetail(null)
    try {
      const normalizedRequest: BriefingRequest = {
        ...request,
        symbol: request.symbol.trim().toUpperCase(),
        as_of: new Date(request.as_of).toISOString(),
      }
      const nextWorkflow = await runResearch(normalizedRequest)
      setWorkflow(nextWorkflow)
      updateRunUrl(nextWorkflow.run_id)
      await pollRunUntilFinished(nextWorkflow.run_id)
      await refreshHistory()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Research workflow failed')
    } finally {
      setLoading(false)
    }
  }

  const runStatus = runDetail?.status ?? workflow?.status
  const headingMeta = useMemo(
    () => (runStatus ? `${request.symbol.toUpperCase()} · ${runStatus}` : 'Ready for a new run'),
    [request.symbol, runStatus],
  )

  const selectSavedRun = (runId: string) => {
    updateRunUrl(runId)
    void showSavedRun(runId)
  }

  const startNewResearch = () => {
    updateRunUrl(null)
    setWorkflow(null)
    setRunDetail(null)
    setError(null)
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
            Briefing
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

          {loading && <LoadingBriefing />}
          {!loading && !error && mode === 'user' && workflow && (
            <BriefingView
              result={workflow}
              symbol={runDetail?.symbol ?? request.symbol}
              asOf={runDetail?.as_of ?? request.as_of}
              timeHorizon={request.time_horizon}
            />
          )}
          {!loading && mode === 'user' && !workflow && !error && (
            <div className="empty-state briefing-empty">
              <span className="empty-index">05</span>
              <strong>Ask a decision-useful question.</strong>
              <p>The agent will retrieve evidence, produce a structured briefing, and verify every finding before returning it.</p>
            </div>
          )}
          {!loading && mode === 'admin' && <AdminView workflow={workflow} run={runDetail} />}
        </div>
        <RunHistory
          runs={runHistory}
          selectedRunId={runDetail?.run_id ?? null}
          loading={historyLoading}
          onSelect={selectSavedRun}
          onNew={startNewResearch}
        />
      </div>
    </section>
  )
}

export default function App() {
  const [selectedTool, setSelectedTool] = useState<ToolDefinition | null>(toolFromLocation)

  useEffect(() => {
    const handleNavigation = () => setSelectedTool(toolFromLocation())
    window.addEventListener('popstate', handleNavigation)
    return () => window.removeEventListener('popstate', handleNavigation)
  }, [])

  const navigateToTool = (tool: ToolDefinition | null) => {
    const url = new URL(window.location.href)
    url.pathname = tool?.id === 'incident-investigation' ? '/incident-investigation' : '/'
    if (tool && tool.id !== 'incident-investigation') url.searchParams.set('tool', tool.id)
    else url.searchParams.delete('tool')
    if (!tool || tool.id !== 'research') url.searchParams.delete('run')
    if (tool?.id === 'incident-investigation') url.searchParams.set('tab', 'run')
    else url.searchParams.delete('tab')
    window.history.pushState({}, '', url)
    setSelectedTool(tool)
  }

  return (
    <div className="app-shell">
      <AppHeader onHome={() => navigateToTool(null)} />
      <div className="app-frame">
        <ToolRail selectedId={selectedTool?.id ?? null} onSelect={navigateToTool} />
        <main className="workspace-canvas">
          {!selectedTool && <ToolCatalog onSelect={navigateToTool} />}
          {selectedTool?.id === 'incident-investigation' && <IncidentWorkspace />}
          {selectedTool?.id === 'research' && <ResearchWorkspace />}
          {selectedTool?.availability === 'planned' && <SystemScaffold tool={selectedTool} />}
        </main>
      </div>
    </div>
  )
}
