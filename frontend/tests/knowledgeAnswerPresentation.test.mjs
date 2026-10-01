import assert from 'node:assert/strict'
import test from 'node:test'

import { presentKnowledgeAnswer } from '../src/knowledgeAnswerPresentation.ts'

test('saved cited answer resolves only its frozen evidence', () => {
  const answer = {
    status: 'completed', stop_reason: 'answered',
    claims: [{ statement: 'Managers approve leave.', evidence_ids: ['K1'] }],
    answer_format: 'numbered_list', action_status: null, action_proposal: null, mock_task: null,
    evidence: [{ evidence_id: 'K1', title: 'Time off policy', excerpt: 'A manager approves leave.', locator: { source_id: 'policy-leave-v1', revision: '2026-09-30', start: 0, end: 25 } }],
  }
  const view = presentKnowledgeAnswer(answer)
  assert.equal(view.status, 'Verified answer')
  assert.equal(view.claims[0].citations[0].locator.source_id, 'policy-leave-v1')
  assert.equal(view.format, 'numbered_list')
})

test('pending mock action presents approval state and an explicit no-task-yet message', () => {
  const view = presentKnowledgeAnswer({
    status: 'completed', stop_reason: 'action_proposal_pending', claims: [], evidence: [],
    answer_format: 'paragraph', action_status: 'pending_approval', mock_task: null,
    action_proposal: { title: 'Follow up on ticket 214', task_type: 'support_follow_up', description: 'Check the refund.', evidence_ids: ['K1'] },
  })
  assert.equal(view.status, 'Awaiting approval')
  assert.equal(view.title, 'Action proposal')
  assert.match(view.message, /No task exists yet/)
})

test('saved abstention has no claims and displays stop reason', () => {
  const view = presentKnowledgeAnswer({ status: 'completed', stop_reason: 'grounding_rejected', claims: [], evidence: [] })
  assert.equal(view.status, 'Abstained')
  assert.equal(view.title, 'grounding rejected')
  assert.match(view.message, /did not sufficiently support/)
  assert.deepEqual(view.claims, [])
})
