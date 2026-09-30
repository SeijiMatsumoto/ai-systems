import type { ResearchWorkflowResult, ResearchWorkflowStep } from './types'

export async function readResearchStream(
  response: Response,
  onStep: (step: ResearchWorkflowStep) => void,
): Promise<ResearchWorkflowResult> {
  if (!response.body) throw new Error('The backend did not return a research stream')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: ResearchWorkflowResult | null = null

  const frame = (text: string) => {
    const event = text.split('\n').find((line) => line.startsWith('event: '))?.slice(7)
    const data = text.split('\n').find((line) => line.startsWith('data: '))?.slice(6)
    if (!event || !data) return
    const payload: unknown = JSON.parse(data)
    if (event === 'step') onStep(payload as ResearchWorkflowStep)
    if (event === 'result') result = payload as ResearchWorkflowResult
    if (event === 'error') {
      const message = payload && typeof payload === 'object' && 'message' in payload
        ? String(payload.message)
        : 'Research stream failed'
      throw new Error(message)
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replaceAll('\r\n', '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        frame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
  } finally {
    reader.releaseLock()
  }
  if (!result) throw new Error('Research stream ended without a result')
  return result
}
