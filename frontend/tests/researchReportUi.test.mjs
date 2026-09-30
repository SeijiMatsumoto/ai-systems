import assert from 'node:assert/strict'
import test from 'node:test'

import { citationKeyword, sourceCount, visibleResearchLimitations } from '../src/researchReportUi.ts'

test('saved reports hide only the four old blanket limitations', () => {
  assert.deepEqual(visibleResearchLimitations([
    'The annual comparison ends with FY2025.',
    'Document searches expose at most three ranked passages per tool call.',
    'Web publication times are provider estimates; extracted pages reflect retrieval-time content.',
    'Current Yahoo snapshot fields are used only for company identity, not cited as historical financial evidence.',
    'Daily close prices on the as-of date are excluded because their intraday availability is unknown.',
  ]), ['The annual comparison ends with FY2025.'])
})

test('citation keywords identify metric period, filing form, and web publisher', () => {
  const revenue = { evidence_type: 'financial', reference_id: 'yahoo:income', field_path: 'periods.0.TotalRevenue', period_end: '2025-09-27' }
  const profit = { ...revenue, field_path: 'periods.0.NetIncome' }
  const filing = { evidence_type: 'document', document_type: 'filing', title: 'Apple Inc. - 10-Q - 2026-07-31', reference_id: 'sec:one' }
  const article = { evidence_type: 'document', document_type: 'article', title: 'Apple update', url: 'https://www.apple.com/newsroom/update', reference_id: 'tavily:one' }
  assert.equal(citationKeyword(revenue), 'Total Revenue FY2025')
  assert.equal(citationKeyword(filing), 'SEC 10-Q')
  assert.equal(citationKeyword(article), 'apple.com')
  assert.equal(sourceCount([revenue, profit, filing]), 2)
})
