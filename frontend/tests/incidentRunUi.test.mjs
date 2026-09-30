import assert from 'node:assert/strict'
import test from 'node:test'

import { currentTask, runIdFromPath, tabFromUrl, withIncidentRun, withIncidentTab } from '../src/incidentRunUi.ts'

const runId = 'e2e499c6-6253-4e36-805c-d9cfcb0a57f8'

test('a new simulation URL selects its ID and Run tab immediately', () => {
  const previous = new URL('http://localhost:5173/incident-investigation/old?tab=result&tool=incident&run=old')
  const next = withIncidentRun(previous, runId, 'run')
  assert.equal(next.pathname, `/incident-investigation/${runId}`)
  assert.equal(next.search, '?tab=run')
  assert.equal(runIdFromPath(next.pathname), runId)
  assert.equal(tabFromUrl(next), 'run')
  assert.equal(previous.pathname, '/incident-investigation/old')
})

test('run selection and tab navigation keep a shareable URL', () => {
  const selected = withIncidentRun(new URL('http://localhost:5173/incident-investigation'), runId, 'result')
  assert.equal(tabFromUrl(selected), 'result')
  assert.equal(runIdFromPath(selected.pathname), runId)
  assert.equal(withIncidentTab(selected, 'run').searchParams.get('tab'), 'run')
  assert.equal(tabFromUrl(new URL(`http://localhost:5173/incident-investigation/${runId}`)), 'result')
  assert.equal(tabFromUrl(new URL('http://localhost:5173/incident-investigation')), 'run')
})

test('current task follows the model and tool loop', () => {
  const step = (stage, status, summary, details = {}) => ({ stage, status, summary, details, sequence: 1, elapsed_ms: 0 })
  assert.match(currentTask(undefined), /Creating the simulation run/)
  assert.match(currentTask(step('classifier', 'running', 'Jev judgment requested')), /Jev is judging/)
  assert.match(currentTask(step('agent', 'running', 'Investigator selected search logs', { tool_name: 'search_logs' })), /search logs/)
  assert.match(currentTask(step('tool', 'completed', 'search logs returned', { tool_name: 'search_logs' })), /interpreting the search logs result/)
  assert.match(currentTask(step('verification', 'running', 'Checking')), /citations/)
})
