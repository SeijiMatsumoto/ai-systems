import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'

import { getIncidentSimulation, getIncidentSimulations, reviewIncidentReport, streamIncidentSimulation } from './api'
import IncidentReviewStage from './IncidentReviewStage'
import { CandidateGateDetails, JevDetails, ReplayGroupDetails, VerifyAndSaveDetails } from './IncidentRunDetails'
import { currentTask, runIdFromPath, tabFromUrl, withIncidentRun, withIncidentTab } from './incidentRunUi'
import type { IncidentTab } from './incidentRunUi'
import type {
  IncidentClaim,
  IncidentEvidence,
  IncidentReport,
  IncidentSimulationResult,
  IncidentSimulationSummary,
  IncidentWorkflowStep,
} from './types'

const LOGFIRE_PROJECT_URL =
  import.meta.env.VITE_LOGFIRE_PROJECT_URL ??
  'https://logfire-us.pydantic.dev/seijim27/ai-systems'

const IncidentSystemDiagram = lazy(() => import('./IncidentSystemDiagram'))
const INCIDENT_PATH = '/incident-investigation'

function runIdAtLocation(): string | null {
  return runIdFromPath(window.location.pathname)
}

function tabFromLocation(): IncidentTab {
  return tabFromUrl(new URL(window.location.href))
}

function updateTabQuery(tab: IncidentTab, replace = false): void {
  const current = new URL(window.location.href)
  if (current.searchParams.get('tab') === tab) return
  const url = withIncidentTab(current, tab)
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url)
}

function updateRunPath(runId: string | null, tab: IncidentTab, replace = false): void {
  const url = withIncidentRun(new URL(window.location.href), runId, tab)
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url)
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

function ReportView({ report, reportId }: { report: IncidentReport; reportId: string }) {
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const evidence = new Map(report.evidence.map((item) => [item.evidence_id, item]))

  useEffect(() => {
    if (!selectedEvidenceId || !evidenceOpen) return
    const frame = requestAnimationFrame(() => {
      document.getElementById(`incident-evidence-${reportId}-${selectedEvidenceId}`)?.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
        block: 'center',
      })
    })
    return () => cancelAnimationFrame(frame)
  }, [selectedEvidenceId, evidenceOpen, reportId])

  const selectEvidence = (id: string) => {
    setSelectedEvidenceId(id)
    setEvidenceOpen(true)
  }

  return (
    <div className="incident-report-detail">
      <section className="incident-report-detail-section" aria-labelledby={`incident-timeline-title-${reportId}`}>
        <div className="incident-panel-heading"><div><p className="section-kicker">Source-backed sequence</p><h3 id={`incident-timeline-title-${reportId}`}>Observed timeline</h3></div><span>{report.timeline.length} observations</span></div>
        <p className="incident-section-note">Facts and correlations in time order. Timing alone does not establish cause.</p>
        <div className="incident-claim-list">
          {report.timeline.map((claim, index) => <ClaimCard key={`${claim.evidence_ids.join('-')}-${index}`} claim={claim} index={index} evidence={evidence} onSelectEvidence={selectEvidence} />)}
        </div>
      </section>

      <section className="incident-report-detail-section" aria-labelledby={`incident-causes-title-${reportId}`}>
        <div className="incident-panel-heading"><div><p className="section-kicker">Assessment</p><h3 id={`incident-causes-title-${reportId}`}>Proposed cause</h3></div><span>Hypothesis, not confirmed</span></div>
        {report.likely_causes.length ? <div className="incident-claim-list">{report.likely_causes.map((claim, index) => <ClaimCard key={`${claim.evidence_ids.join('-')}-${index}`} claim={claim} index={index} evidence={evidence} onSelectEvidence={selectEvidence} />)}</div> : <p className="incident-section-note">No supported candidate cause was identified.</p>}
      </section>

      <div className="incident-report-detail-pair">
        <section className="incident-report-detail-section" aria-labelledby={`incident-unknowns-title-${reportId}`}>
          <p className="section-kicker">Limits</p><h3 id={`incident-unknowns-title-${reportId}`}>What remains unknown</h3>
          {report.unknowns.length ? <ul className="incident-text-list">{report.unknowns.map((unknown, index) => <li key={`${unknown}-${index}`}>{unknown}</li>)}</ul> : <p className="incident-section-note">No unknowns were listed.</p>}
          {report.coverage_gaps.map((gap, index) => <div className="incident-gap" key={`${gap.service}-${gap.start}-${index}`}><strong>{gap.service} · {gap.source} gap</strong><span>{utcTime(gap.start)}–{utcTime(gap.end)} UTC</span><p>{gap.reason}</p></div>)}
        </section>
        <section className="incident-report-detail-section" aria-labelledby={`incident-checks-title-${reportId}`}>
          <p className="section-kicker">Follow-up</p><h3 id={`incident-checks-title-${reportId}`}>Next checks</h3>
          {report.next_checks.length ? <ol className="incident-text-list">{report.next_checks.map((check, index) => <li key={`${check}-${index}`}>{check}</li>)}</ol> : <p className="incident-section-note">No next checks were proposed.</p>}
        </section>
      </div>

      <details className="incident-evidence-disclosure" open={evidenceOpen} onToggle={(event) => setEvidenceOpen(event.currentTarget.open)}>
        <summary><span><strong>Evidence ledger</strong><small>{report.evidence.length} exact fixture records cited above</small></span><span aria-hidden="true">⌄</span></summary>
        <div className="incident-evidence-list">
          {report.evidence.map((item) => <article id={`incident-evidence-${reportId}-${item.evidence_id}`} className={`incident-evidence-item ${selectedEvidenceId === item.evidence_id ? 'selected' : ''}`} key={item.evidence_id}><div className="incident-evidence-meta"><strong>{item.evidence_id}</strong><span>{item.source} · {item.service}</span></div><time dateTime={item.observed_at}>{utcTime(item.observed_at)} UTC</time><p>{item.excerpt}</p><code>{item.locator}</code></article>)}
        </div>
      </details>
    </div>
  )
}

function SystemFlowchart() {
  const [open, setOpen] = useState(false)
  return (
    <details className="incident-architecture" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary><span>System architecture</span><strong>Explore the incident system design</strong><span aria-hidden="true">⌄</span></summary>
      {open && <>
        <p className="incident-diagram-note">The log stream keeps feeding candidate detection throughout the simulation. Only threshold-crossing candidates go to Jev. Expand the investigation stage below to see the actual model choices and tool results.</p>
        <Suspense fallback={<p className="incident-diagram-note">Loading diagram…</p>}>
          <IncidentSystemDiagram />
        </Suspense>
      </>}
    </details>
  )
}

function AgentLoopView({ steps, live }: { steps: IncidentWorkflowStep[]; live: boolean }) {
  const choices = steps.filter((step) => step.stage === 'agent' && step.summary.startsWith('Investigator selected '))
  const tools = steps.filter((step) => step.stage === 'tool')
  const draft = steps.find((step) => step.stage === 'agent' && step.summary === 'Investigator returned a draft')
  const failure = steps.find((step) => step.stage === 'agent' && step.status === 'failed')
  if (!choices.length && !draft && !failure && !steps.some((step) => step.stage === 'agent')) return null

  return (
    <section className="incident-panel incident-agent-loop" aria-labelledby="incident-agent-loop-title">
      <div className="incident-panel-heading">
        <div><p className="section-kicker">04 / Bounded agent loop</p><h2 id="incident-agent-loop-title">Investigator ↔ telemetry tools</h2></div>
        <span>{live ? 'Live · ' : ''}{choices.length} / 8 tool choices</span>
      </div>
      <p className="incident-section-note">Each model tool choice is followed by a scoped Python query and a result. The next model request can use that result. Private reasoning is unavailable.</p>
      <div className="incident-loop-iterations">
        {choices.map((choice, index) => {
          const nextChoice = choices[index + 1]
          const tool = tools.find((item) => item.sequence > choice.sequence && (!nextChoice || item.sequence < nextChoice.sequence))
          const toolName = String(choice.details.tool_name ?? 'telemetry query')
          const returnedIds = tool?.details.returned_evidence_ids
          return (
            <article className="incident-loop-iteration" key={choice.sequence}>
              <span className="incident-loop-number">Loop {index + 1}</span>
              <div className="incident-loop-action"><small>MODEL CHOICE ↓</small><strong>{toolName.replaceAll('_', ' ')}</strong><details><summary>Exact tool arguments</summary><pre>{JSON.stringify(choice.details.arguments, null, 2)}</pre></details></div>
              <div className="incident-loop-action"><small>PYTHON TOOL RESULT ↺</small><strong>{tool ? tool.summary : 'Waiting for tool result…'}</strong>{Array.isArray(returnedIds) && <span>{returnedIds.length} evidence IDs returned</span>}{tool && <details><summary>Exact tool response</summary><pre>{JSON.stringify(tool.details, null, 2)}</pre></details>}</div>
              {index < choices.length - 1 && <span className="incident-loop-next">Result feeds the next model request ↓</span>}
            </article>
          )
        })}
        {!choices.length && <p className="incident-section-note">Investigator started; waiting for its first decision.</p>}
      </div>
      {(draft || failure) && <p className="incident-loop-exit">{draft ? 'Model returned a draft → citation verification' : String(failure?.details.failure_detail ?? failure?.summary)}</p>}
    </section>
  )
}

function RunStage({ number, title, state, description, children }: { number: string; title: string; state: string; description: string; children: React.ReactNode }) {
  const heading = <><span className="incident-stage-number">{number}</span><span className="incident-stage-copy"><strong>{title}</strong><small>{description}</small></span><span className="incident-stage-state">{state}</span></>
  return (
    <li className="incident-run-stage">
      <details><summary>{heading}<span className="incident-stage-chevron" aria-hidden="true">⌄</span></summary><div className="incident-stage-body">{children}</div></details>
    </li>
  )
}

export default function IncidentWorkspace() {
  const [maxReports, setMaxReports] = useState(1)
  const [result, setResult] = useState<IncidentSimulationResult | null>(null)
  const [liveSteps, setLiveSteps] = useState<IncidentWorkflowStep[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<IncidentSimulationSummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [currentRunId, setCurrentRunId] = useState<string | null>(runIdAtLocation)
  const [activeTab, setActiveTab] = useState<IncidentTab>(tabFromLocation)
  const startedNewRun = useRef(false)
  const selectionRequest = useRef(0)
  const selectedRunId = useRef<string | null>(null)

  const selectSavedRun = useCallback(async (runId: string, urlMode: 'push' | 'replace' | 'none' = 'push') => {
    if (!runId) return
    const requestId = ++selectionRequest.current
    try {
      setHistoryError(null)
      const saved = await getIncidentSimulation(runId)
      if (requestId !== selectionRequest.current) return
      selectedRunId.current = saved.run_id
      setCurrentRunId(saved.run_id)
      setResult(saved)
      setLiveSteps([])
      setError(null)
      setActiveTab(urlMode === 'none' ? tabFromLocation() : 'result')
      if (urlMode === 'none') updateTabQuery(tabFromLocation(), true)
      else updateRunPath(saved.run_id, 'result', urlMode === 'replace')
    } catch (cause) {
      if (requestId === selectionRequest.current) {
        setHistoryError(cause instanceof Error ? cause.message : 'Could not open that saved simulation run.')
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const pathRunId = runIdAtLocation()
    if (pathRunId) void selectSavedRun(pathRunId, 'none')
    const restoreLatest = async () => {
      try {
        const saved = await getIncidentSimulations()
        if (cancelled) return
        setHistory(saved)
        if (!pathRunId && !startedNewRun.current && saved[0]) {
          await selectSavedRun(saved[0].run_id, 'replace')
        }
      } catch (cause) {
        if (!cancelled) setHistoryError(cause instanceof Error ? cause.message : 'Could not load saved simulation runs from the database.')
      } finally {
        if (!cancelled) setHistoryLoading(false)
      }
    }
    const handleNavigation = () => {
      if (!window.location.pathname.startsWith(INCIDENT_PATH)) return
      const runId = runIdAtLocation()
      setCurrentRunId(runId)
      setActiveTab(tabFromLocation())
      if (runId && runId !== selectedRunId.current) void selectSavedRun(runId, 'none')
      else {
        if (!runId) {
          selectionRequest.current += 1
          selectedRunId.current = null
          setResult(null)
          setLiveSteps([])
          setError(null)
        }
      }
    }
    void restoreLatest()
    window.addEventListener('popstate', handleNavigation)
    return () => { cancelled = true; selectionRequest.current += 1; window.removeEventListener('popstate', handleNavigation) }
  }, [selectSavedRun])

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    startedNewRun.current = true
    const requestId = ++selectionRequest.current
    const runId = crypto.randomUUID()
    selectedRunId.current = runId
    setCurrentRunId(runId)
    updateRunPath(runId, 'run')
    setLoading(true)
    setError(null)
    setResult(null)
    setLiveSteps([])
    setActiveTab('run')
    try {
      const completed = await streamIncidentSimulation(maxReports, runId, (step) => {
        if (requestId !== selectionRequest.current) return
        if (step.stage !== 'replay' || (step.details.log as { level?: string } | undefined)?.level === 'ERROR') {
          setLiveSteps((previous) => [...previous, step])
        }
      })
      if (requestId !== selectionRequest.current) return
      if (completed.run_id !== runId) throw new Error('The backend returned a different simulation run ID.')
      selectedRunId.current = completed.run_id
      setCurrentRunId(completed.run_id)
      setResult(completed)
      setActiveTab('result')
      updateRunPath(completed.run_id, 'result', true)
      void getIncidentSimulations().then(setHistory).catch((cause: unknown) => {
        setHistoryError(cause instanceof Error ? cause.message : 'Could not refresh saved simulation runs from the database.')
      })
    } catch (cause) {
      if (requestId !== selectionRequest.current) return
      selectedRunId.current = null
      setCurrentRunId(null)
      setError(cause instanceof Error ? cause.message : 'The simulation request failed.')
      setActiveTab('result')
      updateRunPath(null, 'result', true)
    } finally {
      setLoading(false)
    }
  }

  const steps = result?.workflow_steps ?? liveSteps
  const replaySteps = steps.filter((step) => step.stage === 'replay' && (step.details.log as { level?: string } | undefined)?.level === 'ERROR')
  const replayedErrors = replaySteps.length
  const signatureGroups = new Set(replaySteps.map((step) => step.details.group_id).filter((id) => typeof id === 'string')).size
  const correlatedClusters = new Set(replaySteps.map((step) => step.details.cluster_id).filter((id) => typeof id === 'string')).size
  const candidates = steps.filter((step) => step.stage === 'guardrail' && step.summary === 'Candidate passed deterministic error threshold').length
  const classifierSteps = steps.filter((step) => step.stage === 'classifier' && step.status !== 'running')
  const classified = classifierSteps.length
  const toolCalls = steps.filter((step) => step.stage === 'tool').length
  const agentStarted = steps.some((step) => step.stage === 'agent')
  const verification = steps.findLast((step) => step.stage === 'verification')
  const jevOutcomes = result
    ? result.classifications.map((item) => `${item.summary.services.join(' / ')}: ${item.outcome.replaceAll('_', ' ')}${item.judgment ? ` (${Math.round(item.judgment.probability * 100)}%)` : ''}`).join(' · ')
    : classifierSteps.map((step) => step.summary.replace('Candidate classified ', '')).join(' · ')
  const showTabs = loading || Boolean(result) || liveSteps.length > 0 || Boolean(error)
  const latestStep = liveSteps.at(-1)
  const taskLabel = result ? `Simulation finished · ${result.stop_reason.replaceAll('_', ' ')}` : error ? 'Simulation stream failed' : currentTask(latestStep)
  return (
    <section className="workspace-view incident-workspace">
      <div className="workspace-heading">
        <div className="workspace-title-row">
          <span className="tool-number-large">01</span>
          <div><h1>Incident Investigation</h1><p>Log replay · Deterministic grouping · Jev gate · Cited report</p></div>
        </div>
        <span className="status-pill status-available">Runnable demo</span>
      </div>
      <div className="incident-intro">
        <div>
          <p className="section-kicker">Synthetic stream / 2026-04-14</p>
          <h2>Let the logs reveal the incident</h2>
          <p>Inspect the synthetic error stream across services. Repeated errors form groups, correlated groups become candidates, and Jev judges whether each warrants a scoped investigation. No alert is supplied up front.</p>
        </div>
        <div className="incident-intro-stat"><strong>55 error logs</strong><span>Fixture v2 · timestamp order</span></div>
      </div>
      <SystemFlowchart />
      <form className="incident-form" onSubmit={submit}>
        <div className="incident-form-heading">
          <div><p className="section-kicker">Simulation controls</p><h2>Simulate incident</h2></div>
          <span>Read-only fixture · no remediation</span>
        </div>
        <div className="incident-report-limit">
          <label htmlFor="incident-max-reports">Maximum reports per replay <strong>{maxReports}</strong></label>
          <input id="incident-max-reports" type="range" min="1" max="3" step="1" value={maxReports} disabled={loading} onChange={(event) => setMaxReports(Number(event.target.value))} />
          <div className="incident-range-labels"><span>1</span><span>2</span><span>3</span></div>
          <p>Defaults to one report. This fixture has one labeled incident; raising the cap changes the limit, not the fixture. The backend still runs one investigator at a time.</p>
        </div>
        <div className="incident-form-footer">
          <p>Deterministic rules filter the stream before Jev. Only accepted candidates can start an investigator.</p>
          <button className="primary-button" type="submit" disabled={loading}>{loading ? 'Simulating…' : 'Simulate incident'}</button>
        </div>
      </form>
      {(currentRunId || historyLoading || history.length > 0 || historyError) && <div className="incident-history">
        <label htmlFor="incident-saved-run">Saved simulations</label>
        <select id="incident-saved-run" value={currentRunId ?? ''} disabled={loading || historyLoading || (!history.length && !result)} onChange={(event) => { void selectSavedRun(event.target.value) }}>
          <option value="">{historyLoading ? 'Loading runs…' : 'Select a saved run'}</option>
          {currentRunId && !history.some((item) => item.run_id === currentRunId) && <option value={currentRunId}>{loading ? 'Running' : result ? 'Saved run' : 'Opening run'} · {currentRunId}</option>}
          {history.map((item) => <option key={item.run_id} value={item.run_id}>{new Date(item.created_at).toLocaleString()} · {item.report_count} report{item.report_count === 1 ? '' : 's'} · {item.status}</option>)}
        </select>
        {historyError && <span role="alert">{historyError}</span>}
      </div>}
      {showTabs && <>
        <div className="incident-tabs" role="tablist" aria-label="Simulation views">
          <button id="incident-run-tab" type="button" role="tab" aria-controls="incident-run-panel" aria-selected={activeTab === 'run'} onClick={() => { setActiveTab('run'); updateTabQuery('run') }}>
            <span>Run</span><small>Five expandable stages</small>
          </button>
          <button id="incident-result-tab" type="button" role="tab" aria-controls="incident-result-panel" aria-selected={activeTab === 'result'} disabled={!result && !error} onClick={() => { setActiveTab('result'); updateTabQuery('result') }}>
            <span>Result</span><small>{result ? `${result.investigations.length} review packet${result.investigations.length === 1 ? '' : 's'} · run ${result.status}` : error ? 'Failed' : 'Available when finished'}</small>
          </button>
        </div>
        <section id="incident-run-panel" className="incident-tab-panel" role="tabpanel" aria-labelledby="incident-run-tab" hidden={activeTab !== 'run'}>
          {error && !liveSteps.length && <p className="incident-section-note">The request failed before any execution steps arrived.</p>}
          {(loading || result || liveSteps.length > 0) && (
            <section className="incident-panel incident-run-overview" aria-labelledby="incident-run-overview-title">
              <div className="incident-panel-heading"><div><p className="section-kicker">Simulation walkthrough</p><h2 id="incident-run-overview-title">What happened</h2></div><span>{result ? result.stop_reason.replaceAll('_', ' ') : 'Live'}</span></div>
              <div className="incident-current-task" role="status" aria-live="polite"><span>{loading ? 'Current task' : 'Run outcome'}</span><strong>{taskLabel}</strong><small>{currentRunId ? `Run ${currentRunId}` : 'Connecting…'}</small></div>
              <p className="incident-section-note">The log replay continues while accepted candidates are investigated. Expand any stage to inspect its inputs, decisions, and records.</p>
              <ol className="incident-run-stages">
                <RunStage number="01" title="Replay and group errors" state={result ? 'Finished' : 'Running'} description={result ? `${replayedErrors} errors considered · ${signatureGroups} groups · ${correlatedClusters} correlated clusters` : `${replayedErrors} error logs considered · grouping by service and message`}><ReplayGroupDetails steps={steps} /></RunStage>
                <RunStage number="02" title="Candidate gate" state={candidates ? 'Triggered' : result ? 'None' : 'Waiting'} description={candidates ? `${candidates} cluster${candidates === 1 ? '' : 's'} crossed 3 distinct error requests in 5 minutes` : result ? 'No correlated error cluster crossed the threshold' : 'Waiting for a correlated error cluster to cross the threshold'}><CandidateGateDetails steps={steps} /></RunStage>
                <RunStage number="03" title="Jev classification" state={classified ? `${classified} judged` : result ? 'Skipped' : steps.some((step) => step.stage === 'classifier') ? 'Judging' : 'Waiting'} description={jevOutcomes || (candidates ? 'Judging bounded candidate evidence…' : 'Only threshold-crossing candidates reach Jev')}><JevDetails steps={steps} /></RunStage>
                <RunStage number="04" title="Agent investigation" state={agentStarted ? result ? 'Finished' : 'Running' : result ? 'Skipped' : 'Waiting'} description={agentStarted ? `${toolCalls} scoped tool result${toolCalls === 1 ? '' : 's'} · ${result?.investigations.length ?? 0} investigation${result?.investigations.length === 1 ? '' : 's'}` : 'Starts only for an accepted incident'}>{agentStarted ? <AgentLoopView steps={steps} live={loading} /> : <p className="incident-section-note">An accepted Jev decision starts the investigator. No agent run has started yet.</p>}</RunStage>
                <RunStage number="05" title="Verify and save" state={result ? result.status === 'failed' ? 'Failed' : 'Finished' : verification ? 'Checking' : 'Waiting'} description={result ? `${verification?.status === 'completed' ? 'Citations checked · ' : ''}${result.stop_reason.replaceAll('_', ' ')} · outcome saved` : verification ? 'Checking citations and report boundaries' : 'The final outcome will be saved in Neon'}><VerifyAndSaveDetails steps={steps} /></RunStage>
              </ol>
            </section>
          )}
        </section>
        <section id="incident-result-panel" className="incident-tab-panel" role="tabpanel" aria-labelledby="incident-result-tab" hidden={activeTab !== 'result'}>
          {error && <div className="workflow-error" role="alert"><strong>Simulation failed</strong><span>{error}</span></div>}
          {result && (
            <div className="incident-output">
              <div className="incident-run-bar">
                <div><span className="incident-run-label">Run {result.run_id}</span><strong>{result.investigations.length} review packet{result.investigations.length === 1 ? '' : 's'} produced · {result.stop_reason.replaceAll('_', ' ')}</strong></div>
                <div className="incident-run-actions">
                  <span className={`status-pill status-${result.status}`}>Run {result.status}</span>
                  {result.logfire_trace_id && <a href={traceUrl(result.logfire_trace_id)} target="_blank" rel="noreferrer">Logfire trace ↗</a>}
                </div>
              </div>
              {result.error_type && <p className="incident-error-type">Failure type: {result.error_type}</p>}
              {!result.investigations.length && <section className="incident-panel"><h2>No incident report produced</h2><p className="incident-section-note">Open Run to review classifier decisions and the stop reason.</p></section>}
              {result.investigations.map((investigation, index) => {
                const detected = result.detected_incidents[index]
                const reportId = detected?.incident_id ?? String(index)
                const review = result.review_decisions?.[reportId]
                return (
                  <section className="incident-investigation-result" key={reportId} aria-label={`Investigation ${index + 1}`}>
                    {investigation.report && detected && <IncidentReviewStage
                      report={investigation.report}
                      detected={detected}
                      reportId={reportId}
                      review={review}
                      onDecision={async (decision, note) => {
                        const updated = await reviewIncidentReport(result.run_id, reportId, decision, note)
                        setResult((current) => current?.run_id === updated.run_id ? updated : current)
                      }}
                    />}
                    {investigation.report ? <details className="incident-full-report"><summary><span><strong>Full report and source records</strong><small>{investigation.report.timeline.length} observations · {investigation.report.evidence.length} cited records · {investigation.report.next_checks.length} next checks</small></span><span aria-hidden="true">⌄</span></summary><ReportView key={reportId} report={investigation.report} reportId={reportId} /></details> : <div className="incident-panel incident-failure"><h2>No verified report</h2><p>{investigation.workflow_steps.findLast((step) => step.stage === 'agent' && step.status === 'failed')?.details.failure_detail as string | undefined ?? investigation.error_type ?? investigation.stop_reason.replaceAll('_', ' ')}</p>{investigation.verification?.issues.map((issue, issueIndex) => <p key={issueIndex}>{issue.code} at {issue.path}</p>)}</div>}
                  </section>
                )
              })}
              <p className="incident-persistence-note">This report and its workflow are saved in the database. Select another saved simulation above to inspect an earlier run.</p>
            </div>
          )}
        </section>
      </>}
      {!loading && !result && !error && <div className="incident-empty"><span className="empty-index">01</span><strong>The log stream is ready.</strong><p>Simulate the stream to watch grouping, classification, scoped investigation, and report verification.</p></div>}
    </section>
  )
}
