import type { ResearchWorkflowStep } from './types'

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
