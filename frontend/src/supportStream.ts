import type { SupportResult, SupportStep } from './supportTypes'

/** Support uses data-only SSE envelopes, unlike the other agents' named events. */
export async function readSupportStream(response: Response, onStep: (step: SupportStep) => void, onStarted: (runId: string) => void): Promise<SupportResult> {
  if (!response.body) throw new Error('The backend did not return a support stream')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: SupportResult | null = null
  const frame = (value: string) => {
    const data = value.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
    if (!data) return
    const event = JSON.parse(data)
    if (event.type === 'started') onStarted(event.run_id)
    if (event.type === 'step') onStep(event.step)
    if (event.type === 'completed') result = event.result
    if (event.type === 'error') throw new Error(event.message ?? 'Support run failed')
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      buffer = buffer.replaceAll('\r\n', '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        frame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
  } finally { reader.releaseLock() }
  if (!result) throw new Error('Support stream ended without a saved result. Reopen this chat to check its history.')
  return result
}
