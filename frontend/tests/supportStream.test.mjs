import assert from 'node:assert/strict'
import test from 'node:test'
import { readSupportStream } from '../src/supportStream.ts'
function response(chunks) {
  return new Response(new ReadableStream({ start(controller) { for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk)); controller.close() } }))
}
test('support data envelopes preserve start, ordered checks, and committed case result across split frames', async () => {
  const steps = []; const starts = []
  const result = await readSupportStream(response([
    'data: {"type":"started","run_id":"r1"}\r\n\r',
    '\n: heartbeat\n\ndata: {"type":"step","step":{"sequence":1,"stage":"proposal_check","details":{"passed":true}}}\n\n',
    'data: {"type":"step","step":{"sequence":2,"stage":"operation_persistence","details":{"case_id":"case-1"}}}\n\ndata: {"type":"completed","result":{"run_id":"r1","review_case":{"case_id":"case-1","status":"pending_review"}}}\n\n',
  ]), step => steps.push(step), id => starts.push(id))
  assert.deepEqual(starts, ['r1']); assert.deepEqual(steps.map(step => step.sequence), [1, 2]); assert.equal(result.review_case.status, 'pending_review')
})
test('support stream keeps visible checks on save failure and rejects missing completion', async () => {
  const steps = []
  await assert.rejects(readSupportStream(response(['data: {"type":"step","step":{"sequence":1,"stage":"proposal_check"}}\n\ndata: {"type":"error","message":"Persistence failed"}\n\n']), step => steps.push(step), () => {}), /Persistence failed/)
  assert.equal(steps.length, 1)
  await assert.rejects(readSupportStream(response([': heartbeat\n\n']), () => {}, () => {}), /without a saved result/)
})
