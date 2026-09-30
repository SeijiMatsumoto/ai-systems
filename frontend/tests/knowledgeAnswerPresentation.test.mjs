import assert from 'node:assert/strict'
import test from 'node:test'

import { presentKnowledgeAnswer } from '../src/knowledgeAnswerPresentation.ts'

test('saved cited answer resolves only its frozen evidence', () => {
  const answer = {
    status: 'completed', stop_reason: 'answered',
    claims: [{ statement: 'Managers approve leave.', evidence_ids: ['K1'] }],
    evidence: [{ evidence_id: 'K1', title: 'Time off policy', excerpt: 'A manager approves leave.', locator: { source_id: 'policy-leave-v1', revision: '2026-09-30', start: 0, end: 25 } }],
  }
  const view = presentKnowledgeAnswer(answer)
  assert.equal(view.status, 'Verified answer')
  assert.equal(view.claims[0].citations[0].locator.source_id, 'policy-leave-v1')
})

test('saved abstention has no claims and displays stop reason', () => {
  const view = presentKnowledgeAnswer({ status: 'completed', stop_reason: 'grounding_rejected', claims: [], evidence: [] })
  assert.equal(view.status, 'Abstained')
  assert.equal(view.title, 'grounding rejected')
  assert.match(view.message, /did not sufficiently support/)
  assert.deepEqual(view.claims, [])
})
