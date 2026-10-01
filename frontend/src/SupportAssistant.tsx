import { useEffect, useRef, useState } from 'react'
import { CitationTooltip } from './components/CitationTooltip'
import { MarkdownContent } from './components/MarkdownContent'
import TaskScroll from './TaskScroll'
import { taskTrail } from './taskTrail'
import { supportOrderSummary } from './supportOrderSummary'
import { supportChats, supportDecide, supportHistory, supportMessage, supportNewChat, supportSignIn } from './supportApi'
import type { SupportConversation, SupportResult, SupportStep, SupportTurn } from './supportTypes'

const LABELS: Record<string, string> = {
  continuation_precheck: 'Checking conversation context', continuation_input: 'Resolving the follow-up', continuation_check: 'Choosing the support task',
  task_created: 'Starting a support task', task_resumed: 'Resuming the saved support task', task_checkpoint: 'Saving task progress',
  request_check: 'Checking the request', intent_input: 'Classifying the request', intent_check: 'Checking intent confidence',
  model_input: 'Choosing the next support step', model_output: 'Support decision received', tool_check: 'Validating tool arguments', tool_result: 'Reading scoped results',
  eligibility_check: 'Checking order eligibility', proposal_check: 'Validating the proposed change', proposal_state_check: 'Checking current order and policy',
  proposal_grounding_input: 'Checking proposal support', proposal_grounding_check: 'Verifying proposal confidence',
  grounding_input: 'Checking answer support', grounding_check: 'Verifying answer confidence', citation_check: 'Checking source references',
  operation_persistence: 'Saving the support outcome', confirmation_check: 'Checking your confirmation', execution_recheck: 'Rechecking current order state',
}
function describe(step: SupportStep) {
  if (step.stage === 'stop') return `Finished · ${String(step.details.reason ?? 'saved').replaceAll('_', ' ')}`
  if (step.stage === 'tool_call') return `Looking up ${String(step.details.name ?? step.details.tool ?? 'support information').replaceAll('_', ' ')}`
  return LABELS[step.stage] ?? step.stage.replaceAll('_', ' ')
}
function setChatUrl(id: string | null) {
  const url = new URL(window.location.href)
  if (id) url.searchParams.set('chat', id); else url.searchParams.delete('chat')
  url.searchParams.delete('run')
  window.history.replaceState({}, '', url)
}
const SUGGESTIONS = ['What are my orders?', 'Can I cancel my unshipped camera order?', 'What is your return policy?']

export default function SupportAssistant() {
  const [setupAttempt, setSetupAttempt] = useState(0)
  const [token, setToken] = useState('')
  const [chat, setChat] = useState('')
  const [chats, setChats] = useState<SupportConversation[]>([])
  const [turns, setTurns] = useState<SupportTurn[]>([])
  const [draft, setDraft] = useState('')
  const [pendingMessage, setPendingMessage] = useState('')
  const [steps, setSteps] = useState<SupportStep[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selectedRun, setSelectedRun] = useState('')
  const controller = useRef<AbortController | null>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const nearBottom = useRef(true)
  const sequence = useRef(0)

  useEffect(() => {
    let active = true
    const cancelRequest = () => { sequence.current++; controller.current?.abort() }
    setBusy(true)
    setError('')
    void (async () => {
      const key = 'support-demo-session:customer-alex'
      let session = sessionStorage.getItem(key)
      if (!session) { session = (await supportSignIn('customer-alex')).token; sessionStorage.setItem(key, session) }
      const savedChats = await supportChats(session)
      if (!active) return
      const requested = new URLSearchParams(window.location.search).get('chat')
      const id = requested && savedChats.some(item => item.conversation_id === requested) ? requested : (await supportNewChat(session)).conversation_id
      const saved = await supportHistory(session, id)
      const currentChats = await supportChats(session)
      if (!active) return
      setToken(session); setChat(id); setTurns(saved); setChats(currentChats); setSelectedRun(saved.at(-1)?.response.run_id ?? '')
      setChatUrl(id)
    })().catch(cause => { if (active) setError(cause instanceof Error ? cause.message : 'Could not open support') }).finally(() => { if (active) setBusy(false) })
    return () => { active = false; cancelRequest() }
  }, [setupAttempt])

  useEffect(() => {
    const element = transcript.current
    if (element && nearBottom.current) element.scrollTo({ top: element.scrollHeight, behavior: 'auto' })
  }, [turns, pendingMessage, steps])

  const open = async (id: string, session = token) => {
    const saved = await supportHistory(session, id)
    setChat(id); setTurns(saved); setSteps([]); setPendingMessage(''); setSelectedRun(saved.at(-1)?.response.run_id ?? '')
    setChatUrl(id); nearBottom.current = true
  }
  const newChat = async () => {
    if (busy) return
    setBusy(true); setError('')
    try {
      const created = await supportNewChat(token)
      await open(created.conversation_id)
      setDraft(''); setChats(await supportChats(token))
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not open a new chat') }
    finally { setBusy(false) }
  }
  const send = async (message = draft, taskId?: string) => {
    if (busy || !message.trim()) return
    const requestId = ++sequence.current
    const abort = new AbortController(); controller.current = abort
    setBusy(true); setError(''); setDraft(''); setPendingMessage(message.trim()); setSteps([]); nearBottom.current = true
    try {
      const result = await supportMessage(token, chat, message.trim(), step => { if (sequence.current === requestId) setSteps(current => [...current, step]) }, () => { if (sequence.current === requestId) setChatUrl(chat) }, abort.signal, taskId)
      if (sequence.current !== requestId) return
      setTurns(current => [...current, { question: message.trim(), response: result }]); setSelectedRun(result.run_id); setPendingMessage(''); setSteps([])
      setChats(await supportChats(token))
    } catch (cause) {
      if (sequence.current !== requestId) return
      setError(cause instanceof Error ? cause.message : 'Support request failed')
      // A stream failure may follow a successful save. Refresh, never retry a mutation automatically.
      try { await open(chat) } catch { /* Keep the streamed steps and failed message visible. */ }
    } finally { if (sequence.current === requestId) setBusy(false) }
  }
  const decide = async (result: SupportResult, decision: 'confirm' | 'reject') => {
    if (busy || !result.pending_action) return
    setBusy(true); setError('')
    try {
      const saved = await supportDecide(token, chat, result.pending_action.proposal_id, decision)
      await open(chat); setSelectedRun(saved.run_id); setChatUrl(chat)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save your decision') }
    finally { setBusy(false) }
  }
  const tickets = new Map<string, number>()
  for (const turn of turns) {
    const ticket = turn.response.review_case
    if (ticket && !tickets.has(ticket.case_id)) tickets.set(ticket.case_id, ticket.ticket_number ?? tickets.size + 1)
  }
  const customerText = (text: string) => {
    let display = text
    for (const [id, number] of tickets) display = display.replaceAll(id, `Ticket #${number}`)
    for (const turn of turns) for (const source of turn.response.evidence) {
      if (source.kind !== 'order') continue
      try {
        const order = JSON.parse(source.text)
        if (order.placed_on) display = display.replaceAll(source.source_id, `order placed ${order.placed_on}`)
      } catch { /* Non-snapshot evidence retains the general order label below. */ }
    }
    return display.replace(/order-[a-zA-Z0-9_-]+/g, 'your order')
  }
  const terminal = new Map(turns.flatMap(turn => turn.response.receipt ? [[turn.response.receipt.proposal_id, turn.response.receipt.outcome] as const] : []))
  const selected = turns.find(turn => turn.response.run_id === selectedRun)?.response ?? turns.at(-1)?.response
  const workflow = busy && steps.length ? steps : selected?.steps ?? []

  return <div className="knowledge-assistant support-assistant">
    {!token ? <section className="knowledge-run-details"><p role="status">{busy ? 'Opening support…' : error}</p>{!busy && <button type="button" className="primary-button" onClick={() => setSetupAttempt(current => current + 1)}>Retry</button>}</section> : <><div className="support-workspace">
      <section className="knowledge-chat" aria-label="Camera shop customer support">
        <header className="knowledge-chat-header"><div className="knowledge-chat-heading"><span className="knowledge-chat-mark" aria-hidden="true">CS</span><div><p className="section-kicker">Aperture · camera equipment</p><h2>Customer support</h2><p>Order help, camera questions, and human review when needed.</p></div></div><div className="knowledge-chat-controls"><button type="button" className="knowledge-new-chat-button" disabled={busy} onClick={() => { void newChat() }}>New chat</button>{busy && !pendingMessage && <span role="status">Working…</span>}<label><span>Saved chats</span><select value={chat} disabled={busy} onChange={event => { setBusy(true); setError(''); void open(event.target.value).catch(cause => setError(cause.message)).finally(() => setBusy(false)) }}>{chats.map(item => <option value={item.conversation_id} key={item.conversation_id}>{new Date(item.created_at).toLocaleString()}{item.busy ? ' · in progress' : ''}</option>)}</select></label></div></header>
        {error && <p className="knowledge-chat-error" role="alert">{error}</p>}
        <div className="knowledge-chat-transcript" ref={transcript} onScroll={() => { const el = transcript.current; if (el) nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90 }}>
          {!turns.length && !pendingMessage && <div className="knowledge-chat-welcome"><span className="knowledge-chat-welcome-mark" aria-hidden="true">CS</span><h3>How can we help?</h3><p>Ask about your order or camera equipment. Refund and return requests go to a human for review.</p><div className="knowledge-chat-suggestions">{SUGGESTIONS.map(message => <button type="button" key={message} disabled={busy} onClick={() => { void send(message) }}>{message}</button>)}</div></div>}
          {turns.map(({ question, response }) => <div className="support-turn" key={response.run_id}>
            <article className="knowledge-chat-message user-message"><span className="knowledge-message-author">You</span><p>{response.receipt ? `${response.receipt.outcome === 'rejected' ? 'Keep order unchanged' : 'Confirm change'} · ${customerText(response.receipt.order_id)}` : customerText(question)}</p></article>
            <article className="knowledge-chat-message assistant-message"><div className="knowledge-assistant-heading"><span className="knowledge-assistant-avatar" aria-hidden="true">CS</span><strong>Aperture support</strong></div>
              <>{!response.pending_action && !response.review_case && <div className="knowledge-answer-claim"><MarkdownContent>{response.review_case ? response.stop_reason === 'provider_or_validation_failure' ? 'I couldn’t retrieve that information. Our support team will help you with this request.' : 'Your request has been sent to our support team. We’ll follow up with you.' : customerText(response.answer)}</MarkdownContent></div>}</>
              {!response.pending_action && !response.review_case && !response.receipt && response.evidence.some(source => source.kind !== 'order' && source.kind !== 'case') && <div className="knowledge-answer-source-list"><span>Sources</span><span className="knowledge-answer-citations">{response.evidence.filter(source => source.kind !== 'order' && source.kind !== 'case').map(source => <CitationTooltip key={source.evidence_id} className="knowledge-citation-chip" label={`${source.kind} · ${source.source_id}`} sourceTitle={source.source_id} excerpt={source.text} metadata={[{ label: 'Locator', value: source.locator }, { label: 'Evidence', value: source.evidence_id }]} />)}</span></div>}
              {response.pending_action && <section className="knowledge-action-proposal"><div className="knowledge-action-proposal-heading"><p className="section-kicker">{response.pending_action.kind === 'cancel_order' ? 'Cancel order' : 'Change shipping address'}</p><span className="knowledge-action-status">{terminal.get(response.pending_action.proposal_id) === 'rejected' ? 'Order unchanged' : terminal.get(response.pending_action.proposal_id) === 'completed' ? 'Completed' : response.pending_action.state === 'pending' ? 'Confirm change' : response.pending_action.state.replaceAll('_', ' ')}</span></div><h4>{supportOrderSummary(response.evidence, response.pending_action.order_id)?.items.join(' · ') ?? 'Order details unavailable'}</h4>{(() => { const order = supportOrderSummary(response.evidence, response.pending_action.order_id); return order ? <p>{order.placedOn && <>Placed {order.placedOn} · </>}Item total {order.total}<br />{response.pending_action?.kind === 'cancel_order' ? 'Cancel all items in this order.' : 'Update the shipping address for this order.'}</p> : <p>We couldn’t identify the items in this order. Please ask us to check the order again before confirming.</p> })()}{response.pending_action.address && <p>{response.pending_action.address.line1}<br />{response.pending_action.address.city}, {response.pending_action.address.postal_code} · {response.pending_action.address.country}</p>}{!terminal.has(response.pending_action.proposal_id) && response.pending_action.state === 'pending' && <><div className="knowledge-action-buttons"><button type="button" className="primary-button" disabled={busy || !supportOrderSummary(response.evidence, response.pending_action.order_id)} onClick={() => { void decide(response, 'confirm') }}>Confirm {response.pending_action.kind === 'cancel_order' ? 'cancellation' : 'address change'}</button><button type="button" className="knowledge-reject-button" disabled={busy} onClick={() => { void decide(response, 'reject') }}>Keep order unchanged</button></div></>}</section>}
              {response.review_case && <section className="knowledge-action-proposal"><div className="knowledge-action-proposal-heading"><p className="section-kicker">Support ticket</p><span className="knowledge-action-status">Pending review</span></div><h4>Ticket #{tickets.get(response.review_case.case_id)}</h4><p className="knowledge-action-message">Our support team will review your request and follow up.</p><button type="button" className="knowledge-new-chat-button" disabled={busy} onClick={() => { void send(`What is the status of case ${response.review_case?.case_id}?`, response.task?.task_id) }}>Check case status</button></section>}

            </article>
          </div>)}
          {pendingMessage && <><article className="knowledge-chat-message user-message"><span className="knowledge-message-author">You</span><p>{pendingMessage}</p></article><article className="knowledge-chat-message assistant-message"><div className="knowledge-assistant-heading"><span className="knowledge-assistant-avatar" aria-hidden="true">CS</span><strong>Aperture support</strong></div>{busy && <p className="knowledge-chat-thinking" role="status">Thinking...</p>}</article></>}
        </div>
        <form className="knowledge-chat-composer" onSubmit={event => { event.preventDefault(); void send() }}><label className="knowledge-chat-input-label" htmlFor="support-message">Message customer support</label><textarea id="support-message" placeholder="Ask about an order, a policy, or camera equipment…" value={draft} maxLength={2000} disabled={busy} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} /><div className="knowledge-composer-footer"><span>Enter to send · Shift+Enter for a new line</span><button className="primary-button" type="submit" disabled={busy || !draft.trim()}>{busy ? 'Working…' : 'Send'}</button></div></form>
      </section>
      <aside className="knowledge-run-details support-admin" id="support-workflow" aria-label="Admin view"><div className="knowledge-run-details-heading"><div><p className="section-kicker">Demo observability</p><h3>Admin view</h3></div><span>{busy ? 'Working…' : selected?.stop_reason.replaceAll('_', ' ')}</span></div><p className="support-admin-note">Internal workflow, evidence checks, and model usage. This panel is for the demo operator.</p><label className="support-admin-run">Inspect message<select value={selectedRun} disabled={busy} onChange={event => setSelectedRun(event.target.value)}><option value="">Latest message</option>{turns.map(turn => <option key={turn.response.run_id} value={turn.response.run_id}>{turn.question.slice(0,70)}</option>)}</select></label>{busy && <TaskScroll items={steps.length ? taskTrail(steps, describe) : [{ key: 'start', label: 'Checking request' }]} active />}<details className="knowledge-answer-walkthrough"><summary>Workflow · {workflow.length} steps</summary><ol className="support-workflow-list">{workflow.map(step => <li key={step.sequence}><details><summary>{describe(step)}</summary><pre>{JSON.stringify(step.details, null, 2)}</pre></details></li>)}</ol></details>{selected && <details className="knowledge-answer-walkthrough"><summary>Verification and usage</summary><p>Fixture {selected.fixture_version} · {selected.embedding_model ?? 'No policy embedding used'}</p><pre className="support-json">{JSON.stringify(selected.usage, null, 2)}</pre><p>Only visible decisions and tool results are recorded. Model private reasoning and provider internals are unavailable.</p></details>}</aside></div>
    </>}
  </div>
}
