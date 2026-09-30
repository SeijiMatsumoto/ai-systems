import assert from 'node:assert/strict'
import test from 'node:test'

import { readKnowledgeStream } from '../src/knowledgeStream.ts'

function responseFromChunks(chunks) {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  }))
}

test('knowledge answer stream preserves ordered steps and cited result', async () => {
  const steps = []
  const response = responseFromChunks([
    'event: step\ndata: {"sequence":1,"stage":"access_filter","status":"completed","summary":"Scoped","details":{"source_ids":["policy-leave-v1"]}}\n',
    '\nevent: step\ndata: {"sequence":2,"stage":"citation_check","status":"completed","summary":"Verified","details":{"checks":[{"passed":true}]}}\n\nevent: result\ndata: {"run_id":"run-1","status":"completed","stop_reason":"answered","claims":[{"statement":"A manager approves leave.","evidence_ids":["K1"]}],"evidence":[{"evidence_id":"K1","excerpt":"Managers approve leave."}]}\n\n',
  ])
  const result = await readKnowledgeStream(response, (step) => steps.push(step))
  assert.deepEqual(steps.map((step) => step.sequence), [1, 2])
  assert.equal(result.claims[0].evidence_ids[0], result.evidence[0].evidence_id)
})

test('knowledge stream exposes failure and missing terminal result', async () => {
  const steps = []
  await assert.rejects(
    readKnowledgeStream(responseFromChunks([
      'event: step\ndata: {"sequence":1,"stage":"model_input","status":"completed","summary":"Sent","details":{}}\n\n',
      'event: error\ndata: {"detail":"DatabaseError"}\n\n',
    ]), (step) => steps.push(step)),
    /DatabaseError/,
  )
  assert.equal(steps.length, 1)
  await assert.rejects(readKnowledgeStream(responseFromChunks([]), () => {}), /without a saved result/)
})
