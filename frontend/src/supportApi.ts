import { readSupportStream } from './supportStream'
import type { SupportConversation, SupportCustomer, SupportResult, SupportStep, SupportTurn } from './supportTypes'
const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
const PREFIX = '/agent/customer_support'
async function request(path: string, token?: string, options?: RequestInit) {
  let response: Response
  try {
    response = await fetch(`${BASE}${PREFIX}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) } })
  } catch { throw new Error(`Cannot reach the backend at ${BASE}. Start ./run from backend/ and retry.`) }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail ?? `Support request failed (${response.status})`)
  }
  return response
}
export async function supportCustomers(): Promise<SupportCustomer[]> { return (await request('/customers')).json() }
export async function supportSignIn(customerId: string): Promise<{ token: string }> { return (await request('/sessions', undefined, { method: 'POST', body: JSON.stringify({ customer_id: customerId }) })).json() }
export async function supportNewChat(token: string): Promise<{ conversation_id: string }> { return (await request('/conversations', token, { method: 'POST' })).json() }
export async function supportChats(token: string): Promise<SupportConversation[]> { return (await request('/conversations', token)).json() }
export async function supportHistory(token: string, chat: string): Promise<SupportTurn[]> { return (await request(`/conversations/${chat}`, token)).json() }
export async function supportMessage(token: string, chat: string, message: string, onStep: (step: SupportStep) => void, onStarted: (id: string) => void, signal: AbortSignal): Promise<SupportResult> {
  return readSupportStream(await request(`/conversations/${chat}/messages/stream`, token, { method: 'POST', body: JSON.stringify({ message }), signal }), onStep, onStarted)
}
export async function supportDecide(token: string, chat: string, proposal: string, decision: 'confirm' | 'reject'): Promise<SupportResult> {
  return (await request(`/conversations/${chat}/proposals/${proposal}/decision`, token, { method: 'POST', body: JSON.stringify({ decision }) })).json()
}
