import { useState } from 'react'

import { streamIncident } from './api'
import type {
  IncidentClaim,
  IncidentEvidence,
  IncidentReport,
  InvestigationRequest,
  InvestigationResult,
  IncidentWorkflowStep,
} from './types'

const DEFAULT_REQUEST: InvestigationRequest = {
  service: 'checkout',
  alert_id: 'alert-0001',
  window_start: '2026-04-14T14:00:00Z',
  window_end: '2026-04-14T14:59:00Z',
}

const LOGFIRE_PROJECT_URL =
  import.meta.env.VITE_LOGFIRE_PROJECT_URL ??
  'https://logfire-us.pydantic.dev/seijim27/ai-systems'

function hasTimezone(value: string): boolean {
  return /(Z|[+-]\d{2}:\d{2})$/i.test(value)
}

function utcTime(value: string): string {
  return new Intl.DateTimeFormat('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  }).format(new Date(value))
}

function traceUrl(traceId: string): string {
  const query = new URLSearchParams({ q: `trace_id='${traceId}'`, last: '14d' })
  return `${LOGFIRE_PROJECT_URL}/?${query.toString()}`
}

function ClaimCard({
  claim,
  index,
  evidence,
  onSelectEvidence,
}: {
  claim: IncidentClaim
  index: number
  evidence: Map<string, IncidentEvidence>
  onSelectEvidence: (id: string) => void
}) {
  const times = claim.evidence_ids
    .map((id) => evidence.get(id)?.observed_at)
    .filter((value): value is string => Boolean(value))
  const firstTime = times.length ? times.sort()[0] : null

  return (
    <article className="incident-claim">
      <div className="incident-claim-rail">
        <span className="incident-claim-index">{String(index + 1).padStart(2, '0')}</span>
        {firstTime && <time dateTime={firstTime}>{utcTime(firstTime)} UTC</time>}
      </div>
      <div className="incident-claim-body">
        <span className={`incident-kind incident-kind-${claim.kind}`}>{claim.kind}</span>
        <p>{claim.statement}</p>
        <div className="incident-citations" aria-label="Evidence citations">
          {claim.evidence_ids.map((id) => (
            <button key={id} type="button" onClick={() => onSelectEvidence(id)}>
              {id} <span aria-hidden="true">↗</span>
            </button>
          ))}
        </div>
      </div>
    </article>
  )
}

function ReportView({ report }: { report: IncidentReport }) {
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null)
  const evidence = new Map(report.evidence.map((item) => [item.evidence_id, item]))

  const selectEvidence = (id: string) => {
    setSelectedEvidenceId(id)
    document.getElementById(`incident-evidence-${id}`)?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
      block: 'center',
    })
  }

  return (
    <div className="incident-result-grid">
      <div className="incident-report-column">
        <section className="incident-panel incident-timeline" aria-labelledby="incident-timeline-title">
          <div className="incident-panel-heading">
            <div>
              <p className="section-kicker">01 / Sequence</p>
              <h2 id="incident-timeline-title">Observed timeline</h2>
            </div>
            <span>{report.timeline.length} cited observations</span>
          </div>
          <p className="incident-section-note">
            Facts and correlations are shown in time order. Timing alone does not establish cause.
          </p>
          <div className="incident-claim-list">
            {report.timeline.map((claim, index) => (
              <ClaimCard
                key={`${claim.evidence_ids.join('-')}-${index}`}
                claim={claim}
                index={index}
                evidence={evidence}
                onSelectEvidence={selectEvidence}
              />
            ))}
          </div>
        </section>

        <section className="incident-panel" aria-labelledby="incident-causes-title">
          <div className="incident-panel-heading">
            <div>
              <p className="section-kicker">02 / Assessment</p>
              <h2 id="incident-causes-title">Candidate causes</h2>
            </div>
            <span>Engineer review required</span>
          </div>
          {report.likely_causes.length ? (
            <div className="incident-claim-list">
              {report.likely_causes.map((claim, index) => (
                <ClaimCard
                  key={`${claim.evidence_ids.join('-')}-${index}`}
                  claim={claim}
                  index={index}
                  evidence={evidence}
                  onSelectEvidence={selectEvidence}
                />
              ))}
            </div>
          ) : (
            <p className="incident-section-note">The investigator did not identify a supported candidate cause.</p>
          )}
        </section>

        <div className="incident-bottom-grid">
          <section className="incident-panel" aria-labelledby="incident-unknowns-title">
            <p className="section-kicker">03 / Limits</p>
            <h2 id="incident-unknowns-title">Unknowns & coverage</h2>
            {report.unknowns.length ? (
              <ul className="incident-text-list">
                {report.unknowns.map((unknown, index) => <li key={`${unknown}-${index}`}>{unknown}</li>)}
              </ul>
            ) : <p className="incident-section-note">No unknowns were listed.</p>}
            {report.coverage_gaps.map((gap, index) => (
              <div className="incident-gap" key={`${gap.service}-${gap.start}-${index}`}>
                <strong>{gap.service} · {gap.source} gap</strong>
                <span>{utcTime(gap.start)}–{utcTime(gap.end)} UTC</span>
                <p>{gap.reason}</p>
              </div>
            ))}
          </section>
          <section className="incident-panel" aria-labelledby="incident-checks-title">
            <p className="section-kicker">04 / Follow-up</p>
            <h2 id="incident-checks-title">Next checks</h2>
            {report.next_checks.length ? (
              <ol className="incident-text-list">
                {report.next_checks.map((check, index) => <li key={`${check}-${index}`}>{check}</li>)}
              </ol>
            ) : <p className="incident-section-note">No next checks were proposed.</p>}
          </section>
        </div>
      </div>

      <aside className="incident-evidence-panel" aria-labelledby="incident-evidence-title">
        <div className="incident-panel-heading">
          <div>
            <p className="section-kicker">Source records</p>
            <h2 id="incident-evidence-title">Evidence ledger</h2>
          </div>
          <span>{report.evidence.length}</span>
        </div>
        <p className="incident-section-note">
          Exact fixture records cited by the report. Select a citation to jump here.
        </p>
        {report.evidence.map((item) => (
          <article
            id={`incident-evidence-${item.evidence_id}`}
            className={`incident-evidence-item ${selectedEvidenceId === item.evidence_id ? 'selected' : ''}`}
            key={item.evidence_id}
          >
            <div className="incident-evidence-meta">
              <strong>{item.evidence_id}</strong>
              <span>{item.source} · {item.service}</span>
            </div>
            <time dateTime={item.observed_at}>{utcTime(item.observed_at)} UTC</time>
            <p>{item.excerpt}</p>
            <code>{item.locator}</code>
          </article>
        ))}
      </aside>
    </div>
  )
}

function ToolTrace({ result }: { result: InvestigationResult }) {
  return (
    <section className="incident-panel incident-tools" aria-labelledby="incident-tools-title">
      <div className="incident-panel-heading">
        <div>
          <p className="section-kicker">Execution path</p>
          <h2 id="incident-tools-title">Tool steps</h2>
        </div>
        <span>{result.tool_steps.length} calls</span>
      </div>
      {result.tool_steps.length ? (
        <div className="incident-step-list">
          {result.tool_steps.map((step) => (
            <details className="incident-step" key={step.sequence}>
              <summary>
                <span className="incident-step-number">{String(step.sequence).padStart(2, '0')}</span>
                <strong>{step.tool_name.replaceAll('_', ' ')}</strong>
                <span className={step.error ? 'incident-step-error' : ''}>
                  {step.error ? 'Blocked' : `${step.returned_evidence_ids.length} records`}
                </span>
                <small>{step.duration_ms} ms</small>
              </summary>
              <div className="incident-step-detail">
                {step.error && <p className="incident-step-error">{step.error}</p>}
                <strong>Query input</strong>
                <pre>{JSON.stringify(step.arguments, null, 2)}</pre>
                <strong>Tool output</strong>
                <pre>{JSON.stringify(step.result, null, 2)}</pre>
                {step.condensed && <p>Metric points were condensed for the agent.</p>}
                {step.truncated && <p>The query result reached its limit.</p>}
                {step.coverage_gaps.map((gap, index) => (
                  <p key={`${gap.service}-${index}`}>Coverage gap: {gap.service} {gap.source}, {utcTime(gap.start)}–{utcTime(gap.end)} UTC.</p>
                ))}
              </div>
            </details>
          ))}
        </div>
      ) : <p className="incident-section-note">No telemetry tools were called.</p>}
    </section>
  )
}

function WorkflowTrace({ steps, live }: { steps: IncidentWorkflowStep[]; live: boolean }) {
  return (
    <section className="incident-panel incident-workflow-trace" aria-labelledby="incident-workflow-title">
      <div className="incident-panel-heading">
        <div>
          <p className="section-kicker">Execution record</p>
          <h2 id="incident-workflow-title">Workflow trace</h2>
        </div>
        <span>{live ? 'Live · ' : ''}{steps.length} steps</span>
      </div>
      <p className="incident-section-note">
        Harness stages, tool inputs and outputs, verification, and run state in order.
        Model private reasoning is not exposed.
      </p>
      {steps.length ? (
        <div className="incident-workflow-list">
          {steps.map((step) => (
            <details className="incident-workflow-step" key={step.sequence}>
              <summary>
                <span className="incident-step-number">{String(step.sequence).padStart(2, '0')}</span>
                <span className="incident-workflow-stage">{step.stage}</span>
                <strong>{step.summary}</strong>
                <span className={`incident-workflow-status status-${step.status}`}>{step.status}</span>
                <small>+{step.elapsed_ms} ms</small>
              </summary>
              <pre>{JSON.stringify(step.details, null, 2)}</pre>
            </details>
          ))}
        </div>
      ) : <p className="incident-section-note">Waiting for the first harness step…</p>}
    </section>
  )
}

export default function IncidentWorkspace() {
  const [request, setRequest] = useState<InvestigationRequest>(DEFAULT_REQUEST)
  const [result, setResult] = useState<InvestigationResult | null>(null)
  const [liveSteps, setLiveSteps] = useState<IncidentWorkflowStep[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (
      !hasTimezone(request.window_start) ||
      !hasTimezone(request.window_end) ||
      Number.isNaN(Date.parse(request.window_start)) ||
      Number.isNaN(Date.parse(request.window_end))
    ) {
      setError('Enter valid ISO 8601 timestamps with a timezone, such as 2026-04-14T14:00:00Z.')
      return
    }
    if (Date.parse(request.window_start) >= Date.parse(request.window_end)) {
      setError('The window start must be before the end.')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    setLiveSteps([])
    try {
      setResult(await streamIncident(request, (step) => {
        setLiveSteps((previous) => [...previous, step])
      }))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The investigation request failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="workspace-view incident-workspace">
      <div className="workspace-heading">
        <div className="workspace-title-row">
          <span className="tool-number-large">01</span>
          <div>
            <h1>Incident Investigation</h1>
            <p>Scoped telemetry · Cited report · Engineer review</p>
          </div>
        </div>
        <span className="status-pill status-available">Runnable demo</span>
      </div>

      <div className="incident-intro">
        <div>
          <p className="section-kicker">Synthetic scenario / 2026-04-14</p>
          <h2>Checkout errors across five services</h2>
          <p>
            Investigate a simulated checkout error spike with logs, metrics, traces, and change records.
            The investigator can query only the fixture and must cite surfaced evidence.
          </p>
        </div>
        <div className="incident-intro-stat">
          <strong>14:00–14:59</strong>
          <span>UTC investigation window</span>
        </div>
      </div>

      <form className="incident-form" onSubmit={submit}>
        <div className="incident-form-heading">
          <div>
            <p className="section-kicker">Simulation input</p>
            <h2>Simulate the incident</h2>
          </div>
          <span>Fixed fixture v1 · read-only telemetry</span>
        </div>
        <div className="incident-form-grid">
          <label><span>Service</span><input value={request.service} readOnly /></label>
          <label><span>Alert ID</span><input value={request.alert_id} readOnly /></label>
          <label>
            <span>Window start · UTC</span>
            <input
              value={request.window_start}
              onChange={(event) => setRequest({ ...request, window_start: event.target.value })}
              spellCheck={false}
            />
          </label>
          <label>
            <span>Window end · UTC</span>
            <input
              value={request.window_end}
              onChange={(event) => setRequest({ ...request, window_end: event.target.value })}
              spellCheck={false}
            />
          </label>
        </div>
        <div className="incident-form-footer">
          <p>The model chooses up to eight scoped queries. No remediation actions are available.</p>
          <button className="primary-button" type="submit" disabled={loading}>
            {loading ? 'Simulating…' : 'Simulate incident'}
          </button>
        </div>
      </form>

      {error && <div className="workflow-error" role="alert"><strong>Request failed</strong><span>{error}</span></div>}
      {loading && <div className="incident-loading" role="status">Simulating the incident and checking citations…</div>}
      {(loading || liveSteps.length > 0 || result) && (
        <WorkflowTrace steps={result?.workflow_steps ?? liveSteps} live={loading} />
      )}

      {result && (
        <div className="incident-output" aria-live="polite">
          <div className="incident-run-bar">
            <div>
              <span className="incident-run-label">Run {result.run_id}</span>
              <strong>{result.report ? 'Report ready for review' : 'No verified report produced'}</strong>
            </div>
            <div className="incident-run-actions">
              <span className={`status-pill status-${result.status}`}>{result.status}</span>
              {result.report?.review_required && <span className="status-pill status-review-required">Engineer review required</span>}
              {result.logfire_trace_id && (
                <a href={traceUrl(result.logfire_trace_id)} target="_blank" rel="noreferrer">Open Logfire trace ↗</a>
              )}
            </div>
          </div>

          {!result.report && (
            <section className="incident-panel incident-failure" aria-labelledby="incident-failure-title">
              <p className="section-kicker">Run stopped</p>
              <h2 id="incident-failure-title">{result.stop_reason.replaceAll('_', ' ')}</h2>
              {result.error_type && <p>Failure type: {result.error_type}</p>}
              {result.verification?.issues.length ? (
                <ul className="incident-text-list">
                  {result.verification.issues.map((issue, index) => (
                    <li key={`${issue.code}-${index}`}>
                      {issue.code.replaceAll('_', ' ')} at <code>{issue.path}</code>
                      {issue.evidence_id && <> · <code>{issue.evidence_id}</code></>}
                    </li>
                  ))}
                </ul>
              ) : <p>The agent stopped before a report passed verification.</p>}
            </section>
          )}

          {result.report && <ReportView key={result.run_id} report={result.report} />}
          <ToolTrace result={result} />
          <p className="incident-persistence-note">
            Report and tool steps are available in this response only. The run ID and status are saved in the shared registry.
          </p>
        </div>
      )}

      {!loading && !result && !error && (
        <div className="incident-empty">
          <span className="empty-index">01</span>
          <strong>The evidence is ready to investigate.</strong>
          <p>Simulate the incident to see the investigator’s queries, cited claims, coverage gaps, and review state.</p>
        </div>
      )}
    </section>
  )
}
