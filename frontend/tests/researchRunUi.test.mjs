import assert from 'node:assert/strict'
import test from 'node:test'

import { researchCurrentTask, researchTabFromUrl, withResearchRun } from '../src/researchRunUi.ts'

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
