import assert from 'node:assert/strict'
import test from 'node:test'

import { readResearchStream } from '../src/researchStream.ts'

function responseFromChunks(chunks) {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } })
}

test('research stream handles split frames and returns after ordered steps', async () => {
  const steps = []
  const response = responseFromChunks([
    'event: step\ndata: {"run_id":"run-1","sequence":1,"stage":"run","status":"completed","summary":"created","details":{},"recorded_at":"2026-09-30T00:00:00Z"}\n',
    '\nevent: step\ndata: {"run_id":"run-1","sequence":2,"stage":"tool","status":"completed","summary":"searched","details":{"result":{"provider_usage":{"credits":1}}},"recorded_at":"2026-09-30T00:00:01Z"}\n\nevent: result\ndata: {"run_id":"run-1","status":"completed","briefing":null,"verification":null}\n\n',
  ])
  const result = await readResearchStream(response, (step) => steps.push(step))
  assert.deepEqual(steps.map((step) => step.sequence), [1, 2])
  assert.equal(steps[1].details.result.provider_usage.credits, 1)
  assert.equal(result.run_id, 'run-1')
})

test('research stream keeps prior steps when the workflow fails', async () => {
  const steps = []
  const response = responseFromChunks([
    'event: step\ndata: {"run_id":"run-2","sequence":1,"stage":"classifier","status":"running","summary":"classifying","details":{},"recorded_at":"2026-09-30T00:00:00Z"}\n\n',
    'event: error\ndata: {"type":"RuntimeError","message":"provider unavailable"}\n\n',
  ])
  await assert.rejects(readResearchStream(response, (step) => steps.push(step)), /provider unavailable/)
  assert.equal(steps[0].run_id, 'run-2')
})

test('research stream reports a missing terminal event', async () => {
  await assert.rejects(readResearchStream(responseFromChunks([]), () => {}), /without a result/)
})
