import type {
  BackfillRequest,
  BackfillResult,
  BriefingRequest,
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
