import assert from 'node:assert/strict'
import test from 'node:test'

import { currentResearchRequest, researchCurrentTask, researchSourceUse, researchTabFromUrl, withResearchRun } from '../src/researchRunUi.ts'

test('each submitted request gets a fresh cutoff even after viewing a saved run', () => {
  const request = { symbol: ' aapl ', as_of: '2025-01-01T00:00:00Z', research_question: 'Question', audience: 'investors', time_horizon: '12m' }
  const current = currentResearchRequest(request, new Date('2026-09-30T12:11:00Z'))
  assert.equal(current.symbol, 'AAPL')
  assert.equal(current.as_of, '2026-09-30T12:10:00.000Z')
  assert.equal(request.as_of, '2025-01-01T00:00:00Z')
})

test('research run and tab stay in a shareable URL', () => {
  const initial = new URL('http://localhost:5173/?tool=research')
  const run = withResearchRun(initial, 'run-123', 'run')
  assert.equal(run.searchParams.get('run'), 'run-123')
  assert.equal(researchTabFromUrl(run), 'run')
  assert.equal(researchTabFromUrl(withResearchRun(run, 'run-123', 'briefing')), 'briefing')
  assert.equal(initial.searchParams.get('run'), null)
})

test('current task follows Jev, tools, verification, and failure', () => {
  const step = (stage, summary, details = {}, status = 'running') => ({ stage, summary, details, status })
  assert.match(researchCurrentTask(undefined), /Creating/)
  assert.match(researchCurrentTask(step('classifier', 'Jev query judgment requested')), /Jev/)
  assert.match(researchCurrentTask(step('tool', 'called', { tool_name: 'search_web' })), /search web/)
  assert.match(researchCurrentTask(step('verification', 'checking')), /cited findings/)
  assert.match(researchCurrentTask(step('persistence', 'failed', {}, 'failed')), /failed/)
})

test('source use distinguishes inspected Tavily passages from cited findings', () => {
  const step = (tool, result) => ({
    stage: 'tool', status: 'completed', details: { tool_name: tool, result },
  })
  const steps = [
    step('search_web', { results: [{ result_id: 'tavily:one' }] }),
    step('inspect_web_results', { evidence_candidates: [{ evidence_id: 'doc:web-one' }, { evidence_id: 'doc:web-two' }] }),
  ]
  const filing = { evidence_type: 'document', reference_id: 'filing-1', evidence_id: 'doc:filing-one' }
  const briefing = { key_findings: [{ evidence: [filing] }] }
  assert.deepEqual(researchSourceUse(steps, briefing), {
    tavilySearches: 1, inspectedCandidates: 2, citedTavilyEvidence: 0, dispositions: [],
  })
  briefing.key_findings[0].evidence.push({ evidence_type: 'document', reference_id: 'tavily:page-one', evidence_id: 'doc:web-one' })
  assert.equal(researchSourceUse(steps, briefing).citedTavilyEvidence, 1)
  steps.push({ stage: 'verification', status: 'completed', summary: 'Final web source dispositions recorded', details: {
    decisions: [{ evidence_id: 'doc:web-two', outcome: 'excluded', reason: 'Repeated a filing.' }],
  } })
  assert.equal(researchSourceUse(steps, briefing).dispositions[0].reason, 'Repeated a filing.')
})
