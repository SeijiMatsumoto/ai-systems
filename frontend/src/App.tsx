import { useEffect, useMemo, useState } from 'react'

import { backfillCompany, getResearchRun, getResearchRuns, runResearch } from './api'
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
}

const TOOLS: ToolDefinition[] = [
  {
    id: 'backtester',
    number: '01',
    title: 'Strategy Backtester',
    shortTitle: 'Backtester',
    category: 'Finance',
    description: 'Translate investment ideas into executable, self-correcting backtests.',
    availability: 'planned',
  },
  {
    id: 'research',
    number: '02',
    title: 'Research Briefing',
    shortTitle: 'Research',
    category: 'Finance',
    description: 'Produce cited company research with deterministic evidence verification.',
    availability: 'ready',
  },
  {
    id: 'risk-sentinel',
    number: '03',
    title: 'Portfolio Risk Sentinel',
    shortTitle: 'Risk Sentinel',
    category: 'Risk',
    description: 'Monitor portfolio signals and escalate material changes for review.',
    availability: 'planned',
  },
  {
    id: 'regulatory-impact',
    number: '04',
    title: 'Regulatory Impact',
    shortTitle: 'Regulatory',
    category: 'Compliance',
    description: 'Map regulatory changes to systems, controls, and operating processes.',
    availability: 'planned',
  },
  {
    id: 'incident-response',
    number: '05',
    title: 'Incident Coordinator',
    shortTitle: 'Incidents',
    category: 'Operations',
    description: 'Coordinate evidence gathering, diagnosis, and human-approved remediation.',
    availability: 'planned',
  },
  {
    id: 'financial-coach',
    number: '06',
    title: 'Financial Wellness',
    shortTitle: 'Wellness',
    category: 'Consumer',
    description: 'Turn personal financial context into an adaptive, explainable plan.',
    availability: 'planned',
  },
  {
    id: 'knowledge-synthesis',
    number: '07',
    title: 'Knowledge Synthesis',
    shortTitle: 'Knowledge',
    category: 'Operations',
    description: 'Surface decisions, conflicts, and dependencies across team knowledge.',
    availability: 'planned',
  },
  {
    id: 'contract-negotiation',
    number: '08',
    title: 'Contract Negotiation',
    shortTitle: 'Contracts',
    category: 'Procurement',
    description: 'Retrieve precedent and model negotiation options within policy boundaries.',
    availability: 'planned',
  },
  {
    id: 'fraud-patterns',
    number: '09',
    title: 'Fraud Pattern Hunter',
    shortTitle: 'Fraud',
    category: 'Risk',
    description: 'Test behavioral fraud hypotheses before promoting detection rules.',
    availability: 'planned',
  },
  {
    id: 'productivity',
    number: '10',
    title: 'Productivity Agent',
    shortTitle: 'Productivity',
    category: 'Work',
    description: 'Plan and adapt work across goals, calendar constraints, and priorities.',
    availability: 'planned',
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

function dateValue(date: Date): string {
  return date.toISOString().slice(0, 10)
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
  company_name: 'Apple Inc.',
  from_date: dateValue(new Date(Date.now() - 365 * 24 * 60 * 60 * 1000)),
  as_of: dateValue(new Date()),
  include_filings: true,
  include_news: true,
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
        1 tool available
      </div>
    </aside>
  )
}

function ToolCatalog({ onSelect }: { onSelect: (tool: ToolDefinition) => void }) {
  return (
    <section className="catalog-view">
      <div className="catalog-intro">
        <p className="section-kicker">Workbench</p>
        <h1>Systems you can operate, inspect, and question.</h1>
        <p>
          A growing collection of Python agent systems built around explicit contracts,
          bounded autonomy, verification, and observable execution.
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

function PlannedTool({ tool }: { tool: ToolDefinition }) {
  return (
    <section className="planned-view">
      <div className="planned-number">{tool.number}</div>
      <StatusPill status="Planned" />
      <h1>{tool.title}</h1>
      <p>{tool.description}</p>
      <div className="planned-note">
        <strong>Not implemented yet</strong>
        <span>
          This workspace is reserved so each system can eventually expose its own
          inputs, outputs, run state, and operational diagnostics.
        </span>
      </div>
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
          <span>Generated research · Evidence should be reviewed before investment decisions</span>
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
          <h2>Corpus backfill</h2>
          <p>Populate filings and topic-bucket news before running research.</p>
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
          <span>Company name</span>
          <input
            value={request.company_name}
            onChange={(event) => setRequest({ ...request, company_name: event.target.value })}
          />
        </label>
        <label>
          <span>From date</span>
          <input
            type="date"
            value={request.from_date}
            onChange={(event) => setRequest({ ...request, from_date: event.target.value })}
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
        {[
          ['include_filings', 'Filings'],
          ['include_news', 'News'],
          ['include_8k', '8-K filings'],
        ].map(([key, label]) => (
          <label key={key}>
            <input
              checked={request[key as keyof Pick<BackfillRequest, 'include_filings' | 'include_news' | 'include_8k'>]}
              onChange={(event) => setRequest({ ...request, [key]: event.target.checked })}
              type="checkbox"
            />
            {label}
          </label>
        ))}
      </div>
      {error && <div className="inline-error">{error}</div>}
      <button className="secondary-button" disabled={loading} onClick={submit} type="button">
        {loading ? 'Backfilling…' : 'Run backfill'}
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
            <span className="tool-number-large">02</span>
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
              <span className="empty-index">02</span>
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
    if (tool) url.searchParams.set('tool', tool.id)
    else url.searchParams.delete('tool')
    if (!tool || tool.id !== 'research') url.searchParams.delete('run')
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
          {selectedTool?.id === 'research' && <ResearchWorkspace />}
          {selectedTool && selectedTool.id !== 'research' && <PlannedTool tool={selectedTool} />}
        </main>
      </div>
    </div>
  )
}
