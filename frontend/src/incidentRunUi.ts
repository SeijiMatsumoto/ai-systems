import type { IncidentWorkflowStep } from './types'

export type IncidentTab = 'run' | 'result'

const INCIDENT_PATH = '/incident-investigation'

export function runIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/incident-investigation\/([^/]+)\/?$/)
  return match ? decodeURIComponent(match[1]) : null
}

export function tabFromUrl(url: URL): IncidentTab {
  const tab = url.searchParams.get('tab')
  return tab === 'run' || tab === 'result' ? tab : runIdFromPath(url.pathname) ? 'result' : 'run'
}

export function withIncidentTab(url: URL, tab: IncidentTab): URL {
  const next = new URL(url)
  next.searchParams.set('tab', tab)
  return next
}

export function withIncidentRun(url: URL, runId: string | null, tab: IncidentTab): URL {
  const next = withIncidentTab(url, tab)
  next.pathname = runId ? `${INCIDENT_PATH}/${encodeURIComponent(runId)}` : INCIDENT_PATH
  next.searchParams.delete('tool')
  next.searchParams.delete('run')
  return next
}

export function currentTask(step: IncidentWorkflowStep | undefined): string {
  if (!step) return 'Creating the simulation run and connecting to the stream'
  if (step.stage === 'replay') return 'Grouping incoming error logs'
  if (step.stage === 'guardrail') return 'Checking an error cluster against the candidate threshold'
  if (step.stage === 'classifier') return step.status === 'running' ? 'Jev is judging a candidate incident' : 'Applying the Jev decision'
  if (step.stage === 'scope') return 'Preparing the trigger-time evidence snapshot'
  if (step.stage === 'tool') return `Investigator is interpreting the ${String(step.details.tool_name ?? 'telemetry').replaceAll('_', ' ')} result`
  if (step.stage === 'agent') return step.summary.startsWith('Investigator selected ') ? `Investigator selected ${String(step.details.tool_name ?? 'a telemetry tool').replaceAll('_', ' ')}` : 'Investigator is choosing a query or drafting the report'
  if (step.stage === 'verification') return 'Checking report citations and evidence scope'
  if (step.summary === 'Simulation run finished') return 'Saving the simulation outcome'
  if (step.summary === 'Simulation run ID reused') return 'Starting the scoped investigation'
  return 'Starting the simulation run'
}
