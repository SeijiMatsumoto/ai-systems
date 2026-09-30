import type { BriefingRequest, ResearchBriefing, ResearchWorkflowStep } from './types'

export function currentResearchRequest(request: BriefingRequest, now = new Date()): BriefingRequest {
  return {
    ...request,
    symbol: request.symbol.trim().toUpperCase(),
    as_of: new Date(now.getTime() - 60_000).toISOString(),
  }
}

export type ResearchTab = 'run' | 'briefing'

export function researchTabFromUrl(url: URL): ResearchTab {
  const tab = url.searchParams.get('tab')
  return tab === 'run' || tab === 'briefing' ? tab : url.searchParams.has('run') ? 'briefing' : 'run'
}

export function withResearchRun(url: URL, runId: string | null, tab: ResearchTab): URL {
  const next = new URL(url)
  next.searchParams.set('tool', 'research')
  if (runId) next.searchParams.set('run', runId)
  else next.searchParams.delete('run')
  next.searchParams.set('tab', tab)
  return next
}

export function researchCurrentTask(step: ResearchWorkflowStep | undefined): string {
  if (!step) return 'Creating the research run'
  if (step.stage === 'scope') return 'Setting the research evidence scope'
  if (step.stage === 'classifier') return step.summary.includes('Jev') ? 'Jev is judging the research request' : 'Checking request relevance'
  if (step.stage === 'prefetch') return 'Preparing company and price context'
  if (step.stage === 'tool') return `Research agent is using ${String(step.details.tool_name ?? 'a source tool').replaceAll('_', ' ')}`
  if (step.stage === 'agent') return 'Research agent is selecting sources or drafting findings'
  if (step.stage === 'verification') return 'Checking the cited findings'
  if (step.stage === 'checkpoint') return 'Saving the agent checkpoint'
  if (step.stage === 'persistence') return step.status === 'failed' ? 'Research run failed' : 'Saving the verified briefing'
  return 'Starting the research run'
}

export function researchSourceUse(steps: ResearchWorkflowStep[], briefing: ResearchBriefing) {
  const completedTools = steps.filter((step) => step.stage === 'tool' && step.status === 'completed')
  const tavilySearches = completedTools.filter((step) => step.details.tool_name === 'search_web').length
  const inspectedCandidates = new Set<string>()
  for (const step of completedTools.filter((item) => item.details.tool_name === 'inspect_web_results')) {
    const result = step.details.result
    if (!result || typeof result !== 'object' || !('evidence_candidates' in result)) continue
    const candidates = result.evidence_candidates
    if (!Array.isArray(candidates)) continue
    for (const candidate of candidates) {
      if (candidate && typeof candidate === 'object' && 'evidence_id' in candidate && typeof candidate.evidence_id === 'string') {
        inspectedCandidates.add(candidate.evidence_id)
      }
    }
  }
  const citedTavilyEvidence = new Set(
    briefing.key_findings.flatMap((finding) => finding.evidence)
      .filter((evidence) => evidence.evidence_type === 'document' && evidence.reference_id.startsWith('tavily:'))
      .map((evidence) => 'evidence_id' in evidence ? evidence.evidence_id : `${evidence.reference_id}:${evidence.chunk_id}`),
  )
  const dispositionStep = [...steps].reverse().find((step) => step.summary === 'Final web source dispositions recorded')
  const dispositions = Array.isArray(dispositionStep?.details.decisions)
    ? dispositionStep.details.decisions.filter((item): item is { evidence_id: string; title?: string; url?: string; outcome: string; reason: string } =>
      Boolean(item && typeof item === 'object' && 'evidence_id' in item && 'outcome' in item && 'reason' in item))
    : []
  return { tavilySearches, inspectedCandidates: inspectedCandidates.size, citedTavilyEvidence: citedTavilyEvidence.size, dispositions }
}
