import assert from 'node:assert/strict'
import test from 'node:test'

import { incidentReviewSummary } from '../src/incidentReviewSummary.ts'

test('review brief surfaces the trigger even when a change leads the timeline', () => {
  const detected = { service: 'checkout', trigger_log_id: 'logs-0133' }
  const report = {
    timeline: [
      { kind: 'fact', statement: 'Fact: Payments pool reduced from 40 to 4.', evidence_ids: ['changes-0002'] },
      { kind: 'correlation', statement: 'Correlation: Payments DB wait rose.', evidence_ids: ['metrics-0420'] },
      { kind: 'fact', statement: 'Fact: Three checkout 503 orders failed.', evidence_ids: ['logs-0115', 'logs-0133'] },
    ],
    likely_causes: [
      { kind: 'hypothesis', statement: 'Hypothesis: Pool reduction contributed to checkout timeouts.', evidence_ids: ['changes-0002', 'logs-0133'] },
    ],
    unknowns: ['Pool saturation is unconfirmed.'],
    evidence: [
      { evidence_id: 'logs-0133', source: 'log', excerpt: 'Payment authorization timed out' },
    ],
  }

  const brief = incidentReviewSummary(report, detected)
  assert.equal(brief.trigger, 'Three checkout 503 orders failed.')
  assert.equal(brief.cause, 'Pool reduction contributed to checkout timeouts.')
  assert.equal(brief.keyUnknown, 'Pool saturation is unconfirmed.')
  assert.deepEqual(brief.triggerEvidenceIds, ['logs-0115', 'logs-0133'])
  assert.deepEqual(brief.supporting.map((item) => item.statement), [
    'Payments pool reduced from 40 to 4.',
    'Payments DB wait rose.',
  ])
})
