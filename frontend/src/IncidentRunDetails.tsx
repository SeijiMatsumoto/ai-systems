import type { IncidentWorkflowStep } from './types'

type ReplayLog = {
  evidence_id: string
  observed_at: string
  service: string
  level: string
  message: string
}

type ReplayDetails = {
  log: ReplayLog
  signature: string
  group_id: string | null
  group_count: number
  cluster_id: string | null
  cluster_services: string[]
  distinct_error_requests: number
  decision: 'routine' | 'below_threshold' | 'candidate' | 'duplicate_candidate'
  reason: string
}

function replayRecords(steps: IncidentWorkflowStep[]): ReplayDetails[] {
  return steps
    .filter((step) => step.stage === 'replay' && (step.details.log as ReplayLog | undefined)?.level === 'ERROR')
    .map((step) => step.details as ReplayDetails)
}

function time(value: string): string {
  return new Date(value).toLocaleTimeString('en-US', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function title(value: string): string {
  return value.replaceAll('_', ' ')
}

export function ReplayGroupDetails({ steps }: { steps: IncidentWorkflowStep[] }) {
  const records = replayRecords(steps)
  const groups = new Map<string, ReplayDetails[]>()
  for (const record of records) {
    if (!record.group_id) continue
    const members = groups.get(record.group_id) ?? []
    members.push(record)
    groups.set(record.group_id, members)
  }
  return (
    <div className="incident-stage-detail">
      <p className="incident-section-note">Errors with the same service and normalized message join a group while consecutive matches remain within five minutes. Open a group to see the error records assigned to it.</p>
      <div className="incident-detail-list">
        {[...groups].map(([id, members]) => <details className="incident-detail-item" key={id}>
          <summary><strong>{members[0].log.service} · {members[0].log.level}</strong><span>{members[0].signature}</span><small>{members.length} log{members.length === 1 ? '' : 's'}</small></summary>
          <div className="incident-detail-content"><p>Group {id} · {time(members[0].log.observed_at)}–{time(members[members.length - 1].log.observed_at)} UTC</p>
            <ul className="incident-record-list">{members.map((member) => <li key={member.log.evidence_id}><code>{member.log.evidence_id}</code><time>{time(member.log.observed_at)} UTC</time><span>{member.log.message}</span></li>)}</ul>
          </div>
        </details>)}
      </div>
      {!groups.size && <p className="incident-section-note">Waiting for the first log.</p>}
    </div>
  )
}

export function CandidateGateDetails({ steps }: { steps: IncidentWorkflowStep[] }) {
  const records = replayRecords(steps)
  const clusters = new Map<string, ReplayDetails[]>()
  for (const record of records) {
    if (!record.cluster_id) continue
    const members = clusters.get(record.cluster_id) ?? []
    members.push(record)
    clusters.set(record.cluster_id, members)
  }
  return (
    <div className="incident-stage-detail">
      <p className="incident-section-note">A correlated error cluster passes once it reaches three distinct error requests in five minutes. Later errors in that cluster do not trigger a second judgment.</p>
      <p className="incident-detail-count">{clusters.size} error clusters considered · {clusters.size ? [...clusters.values()].filter((members) => members.some((member) => member.decision === 'candidate')).length : 0} passed</p>
      <div className="incident-detail-list">
        {[...clusters].map(([id, members]) => {
          const passed = members.some((member) => member.decision === 'candidate')
          const last = members[members.length - 1]
          return <details className="incident-detail-item" key={id}>
            <summary><strong>{id}</strong><span>{last.cluster_services.join(' / ')} · up to {Math.max(...members.map((member) => member.distinct_error_requests))} distinct error requests</span><small className={passed ? 'incident-decision-pass' : ''}>{passed ? 'Passed' : 'Below threshold'}</small></summary>
            <div className="incident-detail-content"><ul className="incident-record-list">{members.map((member) => <li key={member.log.evidence_id}><code>{member.log.evidence_id}</code><time>{time(member.log.observed_at)} UTC</time><span>{member.log.service} · {member.log.level} · {member.distinct_error_requests} requests · {title(member.decision)}. {member.reason}</span></li>)}</ul></div>
          </details>
        })}
      </div>
      {!clusters.size && <p className="incident-section-note">No error cluster has appeared yet.</p>}
    </div>
  )
}

export function JevDetails({ steps }: { steps: IncidentWorkflowStep[] }) {
  const requests = steps.filter((step) => step.stage === 'classifier' && step.status === 'running')
  const outcomes = steps.filter((step) => step.stage === 'classifier' && step.status !== 'running')
  return (
    <div className="incident-stage-detail">
      <p className="incident-section-note">Each threshold-crossing candidate sends a bounded evidence summary to Jev. The application applies the probability thresholds and records the resulting decision.</p>
      <div className="incident-detail-list">
        {requests.map((request, index) => {
          const outcome = outcomes.find((step) => step.sequence > request.sequence && (requests[index + 1] === undefined || step.sequence < requests[index + 1].sequence))
          const state = request.details.state as Record<string, unknown> | undefined
          const judgment = outcome?.details.judgment as Record<string, unknown> | null | undefined
          return <details className="incident-detail-item" key={request.sequence}>
            <summary><strong>{String(state?.cluster_id ?? `Candidate ${index + 1}`)}</strong><span>{Array.isArray(state?.services) ? state.services.join(' / ') : 'Candidate evidence'} · {String(state?.distinct_error_requests_last_5m ?? '?')} error requests</span><small>{outcome ? title(String(outcome.details.outcome ?? 'unknown')) : 'Judging'}</small></summary>
            <div className="incident-detail-content">
              <p>Model {String(request.details.model)} · question version {String(request.details.question_version)} · timeout {String(request.details.timeout_seconds)}s</p>
              <p>{String(request.details.question)}</p>
              <details><summary>Exact evidence sent to Jev</summary><pre>{JSON.stringify(state, null, 2)}</pre></details>
              {outcome && <><p>Decision: <strong>{title(String(outcome.details.outcome))}</strong>{judgment ? ` · ${Math.round(Number(judgment.probability) * 100)}% incident probability` : ''}{outcome.details.error_type ? ` · ${String(outcome.details.error_type)}` : ''}</p><details><summary>Exact classifier result and thresholds</summary><pre>{JSON.stringify(outcome.details, null, 2)}</pre></details></>}
            </div>
          </details>
        })}
      </div>
      {!requests.length && <p className="incident-section-note">No cluster has crossed the deterministic candidate gate.</p>}
    </div>
  )
}

export function VerifyAndSaveDetails({ steps }: { steps: IncidentWorkflowStep[] }) {
  const checks = steps.filter((step) => step.stage === 'scope' || step.stage === 'verification' || (step.stage === 'registry' && step.summary === 'Simulation run finished'))
  return (
    <div className="incident-stage-detail">
      <p className="incident-section-note">Trigger-time scoping limits available evidence. Citation verification checks the draft before the final simulation outcome is saved.</p>
      <div className="incident-detail-list">{checks.map((step) => <details className="incident-detail-item" key={step.sequence}>
        <summary><strong>{title(step.stage)}</strong><span>{step.summary}</span><small>{title(step.status)}</small></summary>
        <div className="incident-detail-content"><pre>{JSON.stringify(step.details, null, 2)}</pre></div>
      </details>)}</div>
      {!checks.length && <p className="incident-section-note">Waiting for an accepted incident or a final outcome.</p>}
    </div>
  )
}
