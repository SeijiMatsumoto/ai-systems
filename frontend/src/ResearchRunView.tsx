import { lazy, Suspense, useState } from 'react'

import { researchCurrentTask } from './researchRunUi'
import type { ResearchRunStatus, ResearchWorkflowStep } from './types'

const ResearchSystemDiagram = lazy(() => import('./ResearchSystemDiagram'))

type Stage = ResearchWorkflowStep['stage']

const STAGES: Array<{ title: string; stages: Stage[]; description: string }> = [
  { title: 'Request and scope', stages: ['run', 'scope'], description: 'The question, cutoff time, and source boundaries' },
  { title: 'Request decision', stages: ['classifier'], description: 'Jev probabilities, application gate, and any fallback' },
  { title: 'Source preparation', stages: ['prefetch'], description: 'Company identity and prior-day price context' },
  { title: 'Research agent and tools', stages: ['agent', 'tool'], description: 'Model-visible input, selected tools, exact arguments, and results' },
  { title: 'Verification and persistence', stages: ['verification', 'checkpoint', 'persistence'], description: 'Evidence checks, repair, saved state, and stop reason' },
]

function JevJudgment({ details }: { details: Record<string, unknown> }) {
  const judgment = details.judgment
  if (!judgment || typeof judgment !== 'object') return null
  const values = judgment as Record<string, unknown>
  const relevant = values.relevance_probability
  const instruction = values.instruction_probability
  if (typeof relevant !== 'number' || typeof instruction !== 'number') return null
  return (
    <div className="research-jev-decision">
      <strong>{String(details.outcome ?? 'judged').replaceAll('_', ' ')}</strong>
      <span>Company relevance {Math.round(relevant * 100)}%</span>
      <span>Instruction attempt {Math.round(instruction * 100)}%</span>
      <small>Application thresholds determine the branch. These probabilities do not prove the request is safe.</small>
    </div>
  )
}

export default function ResearchRunView({
  steps,
  runId,
  resumedFrom,
  loading,
  status,
  error,
}: {
  steps: ResearchWorkflowStep[]
  runId: string | null
  resumedFrom: string | null
  loading: boolean
  status: ResearchRunStatus | null
  error: string | null
}) {
  const [architectureOpen, setArchitectureOpen] = useState(false)
  const current = steps.at(-1)
  const last = steps.findLast((step) => step.stage === 'persistence')
  const task = loading ? researchCurrentTask(current) : last?.summary ?? (error ? 'Research run failed' : status === 'completed' ? 'Briefing saved' : 'Ready to research')

  return (
    <div className="research-run-view">
      <section className="research-run-overview" aria-label="Research run status">
        <span className="section-kicker">Research walkthrough</span>
        <h2>What happened</h2>
        <div className="research-current-task" role="status" aria-live="polite">
          <span>{loading ? 'Current task' : 'Run outcome'}</span>
          <strong>{task}</strong>
          <small>{runId ? `Run ${runId}` : 'Run ID appears when the first step arrives'}</small>
        </div>
        {resumedFrom && <p className="research-run-note">This attempt resumed from failed run <code>{resumedFrom}</code>. Earlier steps remain with that run.</p>}
        <p className="research-run-note">These are application-recorded inputs, decisions, tool calls, and checks. Model private reasoning and provider internals are unavailable.</p>
      </section>

      <details className="research-architecture" onToggle={(event) => setArchitectureOpen(event.currentTarget.open)}>
        <summary><span>System architecture</span><strong>Explore the research system design</strong><span aria-hidden="true">⌄</span></summary>
        {architectureOpen && <Suspense fallback={<p className="research-run-note">Loading diagram…</p>}><ResearchSystemDiagram /></Suspense>}
      </details>

      {!steps.length && <section className="research-run-overview"><p>{runId ? 'This saved run predates workflow-step recording.' : 'Submit a request to watch the workflow.'}</p></section>}

      {steps.length > 0 && (
        <ol className="research-run-stages">
          {STAGES.map((group, index) => {
            const matching = steps.filter((step) => group.stages.includes(step.stage))
            const currentStageIndex = STAGES.findLastIndex((item) => steps.some((step) => item.stages.includes(step.stage)))
            const state = matching.at(-1)?.status === 'failed' ? 'Failed' : matching.length ? loading && index === currentStageIndex ? 'Running' : 'Recorded' : 'Waiting'
            return (
              <li key={group.title} className="research-run-stage">
                <details open={loading && state === 'Running'}>
                  <summary>
                    <span className="research-stage-number">{String(index + 1).padStart(2, '0')}</span>
                    <span className="research-stage-heading"><strong>{group.title}</strong><small>{group.description}</small></span>
                    <span className="research-stage-state">{state}</span>
                    <span aria-hidden="true">⌄</span>
                  </summary>
                  <div className="research-stage-body">
                    {!matching.length && <p>No steps recorded for this stage.</p>}
                    {matching.map((step) => (
                      <article className={`research-step research-step-${step.status}`} key={`${step.run_id}-${step.sequence}`}>
                        <div className="research-step-heading"><span>{String(step.sequence).padStart(2, '0')} · {step.stage.replaceAll('_', ' ')}</span><strong>{step.summary}</strong><small>{step.status}</small></div>
                        <JevJudgment details={step.details} />
                        {Object.keys(step.details).length > 0 && (
                          <details className="research-step-payload"><summary>Exact recorded inputs and results</summary><pre>{JSON.stringify(step.details, null, 2)}</pre></details>
                        )}
                      </article>
                    ))}
                  </div>
                </details>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
