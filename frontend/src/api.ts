import type {
  BackfillRequest,
  BackfillResult,
  BriefingRequest,
  InvestigationRequest,
  InvestigationResult,
  IncidentSimulationResult,
  IncidentSimulationSummary,
  IncidentWorkflowStep,
  ResearchRunDetail,
  ResearchRunSummary,
  ResearchWorkflowResult,
} from './types'

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })

  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String(payload.detail)
        : `Request failed with status ${response.status}`
    throw new Error(detail)
  }

  return (await response.json()) as T
}

export function runResearch(
  request: BriefingRequest,
): Promise<ResearchWorkflowResult> {
  return apiRequest('/agent/research_brief', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export function runIncident(
  request: InvestigationRequest,
): Promise<InvestigationResult> {
  return apiRequest('/agent/incident_investigation', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

async function streamIncidentWorkflow<T>(
  path: string,
  request: Record<string, unknown>,
  onStep: (step: IncidentWorkflowStep) => void,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  } catch {
    throw new Error(`Cannot reach the backend at ${API_BASE_URL}. Start ./run from backend/ and retry.`)
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    const detail = payload && typeof payload === 'object' && 'detail' in payload
      ? String(payload.detail)
      : `Investigation request failed with status ${response.status}`
    throw new Error(detail)
  }
  if (!response.body) throw new Error('The backend did not return a workflow stream')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: T | null = null

  const handleFrame = (frame: string) => {
    const event = frame.split('\n').find((line) => line.startsWith('event: '))?.slice(7)
    const data = frame.split('\n').find((line) => line.startsWith('data: '))?.slice(6)
    if (!event || !data) return
    const payload: unknown = JSON.parse(data)
    if (event === 'step') onStep(payload as IncidentWorkflowStep)
    if (event === 'result') result = payload as T
    if (event === 'error') {
      const detail = payload && typeof payload === 'object' && 'detail' in payload
        ? String(payload.detail)
        : 'Investigation stream failed'
      throw new Error(detail)
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      handleFrame(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
    }
    if (done) break
  }
  if (!result) throw new Error('Investigation stream ended without a result')
  return result
}

export function streamIncident(
  request: InvestigationRequest,
  onStep: (step: IncidentWorkflowStep) => void,
): Promise<InvestigationResult> {
  return streamIncidentWorkflow<InvestigationResult>(
    '/agent/incident_investigation/stream',
    { ...request },
    onStep,
  )
}

export function streamIncidentSimulation(
  maxReports: number,
  runId: string,
  onStep: (step: IncidentWorkflowStep) => void,
): Promise<IncidentSimulationResult> {
  return streamIncidentWorkflow<IncidentSimulationResult>(
    '/agent/incident_investigation/simulate/stream',
    { run_id: runId, max_reports: maxReports, replay_delay_ms: 25 },
    onStep,
  )
}

export function getIncidentSimulations(limit = 10): Promise<IncidentSimulationSummary[]> {
  return apiRequest(`/agent/incident_investigation/simulations?limit=${limit}`)
}

export function getIncidentSimulation(runId: string): Promise<IncidentSimulationResult> {
  return apiRequest(`/agent/incident_investigation/simulations/${runId}`)
}

export function reviewIncidentReport(
  runId: string,
  incidentId: string,
  decision: 'approved' | 'changes_requested',
  note: string,
): Promise<IncidentSimulationResult> {
  return apiRequest(
    `/agent/incident_investigation/simulations/${runId}/reviews/${encodeURIComponent(incidentId)}`,
    { method: 'POST', body: JSON.stringify({ decision, note }) },
  )
}

export function getResearchRun(runId: string): Promise<ResearchRunDetail> {
  return apiRequest(`/research-runs/${runId}`)
}

export function getResearchRuns(limit = 20): Promise<ResearchRunSummary[]> {
  return apiRequest(`/research-runs?limit=${limit}`)
}

export function backfillCompany(
  request: BackfillRequest,
): Promise<BackfillResult> {
  return apiRequest('/ingestion/company-backfill', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}
