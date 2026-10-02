import assert from 'node:assert/strict'
import test from 'node:test'
import { supportOrderSummary } from '../src/supportOrderSummary.ts'
const source = { kind: 'order', source_id: 'order-1001', text: JSON.stringify({ order_id: 'order-1001', placed_on: '2026-09-30', lines: [{ product_name: 'Canon EOS R50', quantity: 2, unit_price_cents: 67900 }] }) }
test('confirmation identifies exact items, date and item total from its own evidence', () => {
  assert.deepEqual(supportOrderSummary([source], 'order-1001'), { items: ['2 × Canon EOS R50'], placedOn: 'September 30, 2026', total: '$1,358.00' })
  assert.equal(supportOrderSummary([source], 'order-1002'), null)
})
test('missing or malformed order details cannot identify a confirmation', () => {
  assert.equal(supportOrderSummary([], 'order-1001'), null)
  assert.equal(supportOrderSummary([{ ...source, text: '{}' }], 'order-1001'), null)
  assert.equal(supportOrderSummary([{ ...source, text: 'invalid' }], 'order-1001'), null)
})
