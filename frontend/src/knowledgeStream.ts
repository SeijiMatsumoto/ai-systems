import type { KnowledgeAnswerResult, KnowledgeStep } from './types'

export async function readKnowledgeStream(
  response: Response,
  onStep: (step: KnowledgeStep) => void,
): Promise<KnowledgeAnswerResult> {
  if (!response.body) throw new Error('The backend did not return an answer stream')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: KnowledgeAnswerResult | null = null
  const handleFrame = (frame: string) => {
    const event = frame.split('\n').find((line) => line.startsWith('event: '))?.slice(7)
    const data = frame.split('\n').find((line) => line.startsWith('data: '))?.slice(6)
    if (!event || !data) return
    const payload: unknown = JSON.parse(data)
    if (event === 'step') onStep(payload as KnowledgeStep)
    if (event === 'result') result = payload as KnowledgeAnswerResult
    if (event === 'error') {
      const detail = payload && typeof payload === 'object' && 'detail' in payload
        ? String(payload.detail) : 'Answer stream failed'
      throw new Error(detail)
    }
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replaceAll('\r\n', '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        handleFrame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
  } finally {
    reader.releaseLock()
  }
  if (!result) throw new Error('Answer stream ended without a saved result')
  return result
}
