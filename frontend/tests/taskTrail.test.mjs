import assert from 'node:assert/strict'
import test from 'node:test'

import { taskTrail } from '../src/taskTrail.ts'

test('task trail collapses consecutive repeats and retains ordered transitions', () => {
  const steps = [
    { sequence: 1, task: 'Checking scope' },
    { sequence: 2, task: 'Checking scope' },
    { sequence: 3, task: 'Searching filings' },
    { sequence: 4, task: 'Checking scope' },
  ]
  assert.deepEqual(taskTrail(steps, (step) => step.task), [
    { key: '1', label: 'Checking scope' },
    { key: '3', label: 'Searching filings' },
    { key: '4', label: 'Checking scope' },
  ])
})

test('completed run adds its outcome without repeating the last task', () => {
  const steps = [{ sequence: 1, task: 'Briefing saved' }]
  assert.equal(taskTrail(steps, (step) => step.task, 'Briefing saved').length, 1)
  assert.equal(taskTrail(steps, (step) => step.task, 'Review required').at(-1).label, 'Review required')
})
