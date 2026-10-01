import { useEffect, useRef, useState } from 'react'

import { buildKnowledgeMockIndex, decideKnowledgeAction, getKnowledgeAnswer, getKnowledgeAnswers, getKnowledgeApprovers, getKnowledgeIndexStatus, getKnowledgePersonas, streamKnowledgeAnswer } from './api'
import { CitationTooltip } from './components/CitationTooltip'
import { MarkdownContent } from './components/MarkdownContent'
import TaskScroll from './TaskScroll'
import { taskTrail } from './taskTrail'
import type { DemoPersona, KnowledgeAnswerResult, KnowledgeAnswerSummary, KnowledgeApprover, KnowledgeConversationContext, KnowledgeEvidence, KnowledgeIndexBuildReport, KnowledgeIndexStatus, KnowledgeStep } from './types'
import { presentKnowledgeAnswer } from './knowledgeAnswerPresentation'

function CitationBadges({ citations }: { citations: KnowledgeEvidence[] }) {
  const uniqueCitations = [...new Map(citations.map((item) => [item.evidence_id, item])).values()]
  if (uniqueCitations.length === 0) return null
  return <span className="knowledge-answer-citations">{uniqueCitations.map((item, index) => <CitationTooltip
    key={item.evidence_id}
    className="knowledge-citation-chip"
    label={`${index + 1}. ${item.title}`}
    sourceTitle={item.title}
    excerpt={item.excerpt}
    metadata={[
      { value: `${item.locator.source_id}@${item.locator.revision}:${item.locator.start}-${item.locator.end}`, code: true },
      { label: 'Chunk', value: item.chunk_id, code: true },
    ]}
  />)}</span>
}

function describeKnowledgeStep(step: KnowledgeStep) {
  if (step.stage === 'stop') {
    const reason = String(step.details.stop_reason ?? '')
    if (reason === 'action_proposal_pending') return 'Proposal ready · awaiting approval'
    if (reason === 'answered') return 'Answer verified'
    if (reason === 'action_executed') return 'Approved task created'
    if (reason === 'action_proposal_rejected') return 'Proposal rejected'
  }
  if (step.stage === 'persistence') return 'Saved answer and workflow'
  return step.summary
}

function KnowledgeClaims({ answer }: { answer: KnowledgeAnswerResult }) {
  const view = presentKnowledgeAnswer(answer)
  if (!view?.claims.length) return null
  const citations = view.claims.flatMap((claim) => claim.citations)
  return <div className={`knowledge-answer-claim knowledge-answer-${view.format}`}>
    {view.format === 'numbered_list' ? <ol>{view.claims.map((claim, index) => <li key={`${index}-${claim.statement}`}><MarkdownContent>{claim.statement}</MarkdownContent></li>)}</ol>
      : view.format === 'bullet_list' ? <ul>{view.claims.map((claim, index) => <li key={`${index}-${claim.statement}`}><MarkdownContent>{claim.statement}</MarkdownContent></li>)}</ul>
        : view.claims.map((claim, index) => <div key={`${index}-${claim.statement}`}><MarkdownContent>{claim.statement}</MarkdownContent></div>)}
    {citations.length > 0 && <div className="knowledge-answer-source-list"><span>Sources</span><CitationBadges citations={citations} /></div>}
  </div>
}

function PreviousKnowledgeTurn({ answer }: { answer: KnowledgeAnswerResult }) {
  const view = presentKnowledgeAnswer(answer)
  return <>
    <article className="knowledge-chat-message user-message">
      <span className="knowledge-message-author">You</span>
      <p>{answer.request.question}</p>
    </article>
    <article className="knowledge-chat-message assistant-message knowledge-previous-answer">
      <div className="knowledge-assistant-heading">
        <span className="knowledge-assistant-avatar" aria-hidden="true">KB</span>
        <strong>Knowledge assistant</strong>
        <span className="knowledge-assistant-status">{view.status}</span>
      </div>
      <KnowledgeClaims answer={answer} />
      {answer.action_proposal && <section className="knowledge-action-history">
        <strong>{answer.action_proposal.title}</strong>
        <MarkdownContent>{answer.action_proposal.description}</MarkdownContent>
        <span>{answer.action_status?.replaceAll('_', ' ')} · Open this run in Saved chats to review the proposal.</span>
      </section>}
      {answer.claims.length === 0 && !answer.action_proposal && <p className="knowledge-answer-abstain">{view.message}</p>}
    </article>
  </>
}

function setRunUrl(runId: string | null) {
  const url = new URL(window.location.href)
  if (runId) url.searchParams.set('run', runId)
  else url.searchParams.delete('run')
  window.history.replaceState({}, '', url)
}

function answerContext(answer: KnowledgeAnswerResult): KnowledgeConversationContext | null {
  const assistantMessage = answer.claims.map((claim) => claim.statement).join('\n')
    || (answer.action_proposal
      ? `${answer.action_proposal.title}\n${answer.action_proposal.description}\nStatus: ${answer.action_status ?? 'pending'}`
      : presentKnowledgeAnswer(answer).message)
  return {
    question: answer.request.question,
    answer: assistantMessage,
  }
}

const ROLE_SUGGESTIONS: Record<string, string[]> = {
  alex: [
    'What receipts do I need for a business expense?',
    'What happens to a customer refund request?',
    'What should support do when a shipment is late?',
  ],
  morgan: [
    'What should I check before a production release?',
    'What details belong in an on-call handoff?',
    'How should I report a lost work device?',
  ],
}

export default function KnowledgeAssistant() {
  const [personas, setPersonas] = useState<DemoPersona[]>([])
  const [approvers, setApprovers] = useState<KnowledgeApprover[]>([])
  const [approverId, setApproverId] = useState('jordan-support-lead')
  const [personaId, setPersonaId] = useState('')
  const [loginPersonaId, setLoginPersonaId] = useState('')
  const [signedIn, setSignedIn] = useState(false)
  const [question, setQuestion] = useState('')
  const [submittedQuestion, setSubmittedQuestion] = useState<string | null>(null)
  const [answer, setAnswer] = useState<KnowledgeAnswerResult | null>(null)
  const [previousTurns, setPreviousTurns] = useState<KnowledgeAnswerResult[]>([])
  const [liveSteps, setLiveSteps] = useState<KnowledgeStep[]>([])
  const [savedAnswers, setSavedAnswers] = useState<KnowledgeAnswerSummary[]>([])
  const [historyError, setHistoryError] = useState('')
  const [indexStatus, setIndexStatus] = useState<KnowledgeIndexStatus | null>(null)
  const [buildReport, setBuildReport] = useState<KnowledgeIndexBuildReport | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const requestSequence = useRef(0)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const answerView = answer ? presentKnowledgeAnswer(answer) : null
  const indexIsMock = indexStatus?.embedding_model === 'mock-embedding-v1'
  const noIndexChanges = buildReport && !buildReport.added_sources.length && !buildReport.updated_sources.length && !buildReport.removed_sources.length && !buildReport.acl_only_sources.length
  const followUpEvidence = answer?.evidence.find((item) => answer.action_evidence_ids.includes(item.evidence_id) && answer.authorized_source_ids.includes(item.locator.source_id))
  const workflowSteps = answer?.steps.length ? answer.steps : liveSteps
  const progressItems = taskTrail(workflowSteps, describeKnowledgeStep)

  useEffect(() => {
    const transcript = transcriptRef.current
    if (!transcript) return
    if (answer || submittedQuestion) transcript.scrollTo({ top: transcript.scrollHeight, behavior: 'smooth' })
  }, [answer, submittedQuestion])

  useEffect(() => {
    let active = true
    Promise.all([getKnowledgePersonas(), getKnowledgeIndexStatus(), getKnowledgeApprovers()]).then(([items, status, approverList]) => {
      if (!active) return
      setPersonas(items)
      setLoginPersonaId((current) => current || items[0]?.persona_id || '')
      setIndexStatus(status)
      setApprovers(approverList)
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Could not load demo personas')
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    getKnowledgeAnswers().then((items) => {
      if (active) setSavedAnswers(items)
    }).catch((cause: unknown) => {
      if (active) setHistoryError(cause instanceof Error ? cause.message : 'Could not load saved answers')
    })
    const runId = new URLSearchParams(window.location.search).get('run')
    if (runId) getKnowledgeAnswer(runId).then((saved) => {
      if (!active) return
      setAnswer(saved)
      setPreviousTurns([])
      setPersonaId(saved.request.persona_id)
      setLoginPersonaId(saved.request.persona_id)
      setSignedIn(true)
      setQuestion('')
      setSubmittedQuestion(saved.request.question)
    }).catch((cause: unknown) => {
      if (active) setHistoryError(cause instanceof Error ? cause.message : 'Could not open saved answer')
    })
    return () => { active = false }
  }, [])

  const reset = () => {
    requestSequence.current += 1
    setAnswer(null)
    setPreviousTurns([])
    setSubmittedQuestion(null)
    setQuestion('')
    setLiveSteps([])
    setRunUrl(null)
    setError('')
    setLoading(false)
    setSignedIn(false)
    setLoginPersonaId(personaId)
  }

  const runAnswer = async (questionOverride?: string) => {
    const submitted = (questionOverride ?? question).trim()
    if (loading || !submitted || !personaId) return
    const sequence = ++requestSequence.current
    const runId = crypto.randomUUID()
    if (answer) setPreviousTurns((previous) => [...previous, answer])
    setSubmittedQuestion(submitted)
    setQuestion('')
    setLoading(true)
    setError('')
    setAnswer(null)
    setLiveSteps([])
    setRunUrl(runId)
    try {
      const priorAnswers = previousTurns.length > 0
        ? previousTurns
        : answer?.request.conversation_context ?? []
      const conversationContext = [
        ...priorAnswers.flatMap((turn) => 'run_id' in turn
          ? (answerContext(turn) ? [answerContext(turn)!] : [])
          : [turn]),
        ...(answer ? (answerContext(answer) ? [answerContext(answer)!] : []) : []),
      ].slice(-6)
      const completed = await streamKnowledgeAnswer(personaId, submitted, runId, conversationContext, (step) => {
        if (sequence === requestSequence.current) setLiveSteps((previous) => [...previous, step])
      })
      if (sequence === requestSequence.current) {
        setAnswer(completed)
        getKnowledgeAnswers().then(setSavedAnswers).catch((cause: unknown) => {
          setHistoryError(cause instanceof Error ? cause.message : 'Could not refresh saved answers')
        })
      }
    } catch (cause) {
      if (sequence === requestSequence.current) setError(cause instanceof Error ? cause.message : 'Answer failed')
    } finally {
      if (sequence === requestSequence.current) setLoading(false)
    }
  }

  const selectSavedAnswer = async (runId: string) => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError('')
    try {
      const saved = await getKnowledgeAnswer(runId)
      if (sequence !== requestSequence.current) return
      setAnswer(saved)
      setPreviousTurns([])
      setLiveSteps([])
      setPersonaId(saved.request.persona_id)
      setLoginPersonaId(saved.request.persona_id)
      setSignedIn(true)
      setQuestion('')
      setSubmittedQuestion(saved.request.question)
      setRunUrl(runId)
    } catch (cause) {
      if (sequence === requestSequence.current) setError(cause instanceof Error ? cause.message : 'Could not open saved answer')
    } finally {
      if (sequence === requestSequence.current) setLoading(false)
    }
  }

  const buildIndex = async () => {
    setLoading(true)
    setError('')
    try {
      const report = await buildKnowledgeMockIndex()
      setBuildReport(report)
      setIndexStatus(await getKnowledgeIndexStatus())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Indexing failed')
    } finally {
      setLoading(false)
    }
  }

  const decideAction = async (decision: 'approve' | 'reject') => {
    if (!answer) return
    setLoading(true)
    setError('')
    try {
      const updated = await decideKnowledgeAction(answer.run_id, approverId, decision)
      setAnswer(updated)
      getKnowledgeAnswers().then(setSavedAnswers).catch((cause: unknown) => {
        setHistoryError(cause instanceof Error ? cause.message : 'Could not refresh saved answers')
      })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record approval')
    } finally {
      setLoading(false)
    }
  }

  const transcriptQuestion = answer?.request.question ?? submittedQuestion

  return (
    <>
    {!signedIn && <section className="knowledge-login" aria-label="Choose demo persona">
      <div className="knowledge-login-card">
        <span className="knowledge-chat-mark" aria-hidden="true">KB</span>
        <p className="section-kicker">Internal assistant</p>
        <h2>Sign in to the knowledge base</h2>
        <p>Choose a demo role to see the policies and documents available to that persona.</p>
        <form onSubmit={(event) => {
          event.preventDefault()
          if (!loginPersonaId || !indexStatus?.ready) return
          setPersonaId(loginPersonaId)
          setSignedIn(true)
          setError('')
        }}>
          <label htmlFor="knowledge-login-persona">Sign in as</label>
          <select id="knowledge-login-persona" value={loginPersonaId} onChange={(event) => setLoginPersonaId(event.target.value)} disabled={!personas.length}>
            {personas.map((item) => <option key={item.persona_id} value={item.persona_id}>{item.label}</option>)}
          </select>
          <p className="knowledge-login-demo-note">Demo sign-in only · this does not authenticate a real user.</p>
          {!indexStatus?.ready && <p className="knowledge-login-error">Build the fixture index before opening a chat.</p>}
          {error && <p className="knowledge-login-error" role="alert">{error}</p>}
          {!indexStatus?.ready && <button type="button" className="knowledge-login-build" onClick={() => { void buildIndex() }} disabled={loading}>{loading ? 'Building index…' : 'Build mock fixture index'}</button>}
          <button className="primary-button" type="submit" disabled={!personas.length || !loginPersonaId || !indexStatus?.ready}>Continue</button>
        </form>
        {savedAnswers.length > 0 && <div className="knowledge-login-saved">
          <label htmlFor="knowledge-saved-chat">Or reopen a saved chat</label>
          <select id="knowledge-saved-chat" defaultValue="" onChange={(event) => { if (event.target.value) void selectSavedAnswer(event.target.value) }} disabled={loading}>
            <option value="">Choose a saved chat…</option>
            {savedAnswers.map((item) => <option key={item.run_id} value={item.run_id}>{new Date(item.created_at).toLocaleString()} · {item.question}</option>)}
          </select>
        </div>}
      </div>
    </section>}

    {signedIn && <>
    <section className="knowledge-chat" aria-label="Internal knowledge assistant">
      <header className="knowledge-chat-header">
        <div className="knowledge-chat-heading">
          <span className="knowledge-chat-mark" aria-hidden="true">KB</span>
          <div>
            <p className="section-kicker">Internal assistant</p>
            <h2>Knowledge base</h2>
            <p>Answers use only passages this demo persona can read.</p>
          </div>
        </div>
        <div className="knowledge-chat-controls">
          <button type="button" className="knowledge-new-chat-button" onClick={reset} aria-label="Start a new chat">New chat</button>
          <span className="knowledge-chat-identity">Signed in as <strong>{personas.find((item) => item.persona_id === personaId)?.label ?? 'Demo user'}</strong></span>
          {savedAnswers.length > 0 && <label>
            <span>Saved chats</span>
            <select value={answer?.run_id ?? ''} onChange={(event) => { if (event.target.value) void selectSavedAnswer(event.target.value) }} disabled={loading}>
              <option value="">Recent conversations</option>
              {savedAnswers.filter((item) => item.persona_id === personaId).map((item) => <option key={item.run_id} value={item.run_id}>{new Date(item.created_at).toLocaleString()} · {item.question} · {item.stop_reason.replaceAll('_', ' ')}</option>)}
            </select>
          </label>}
        </div>
      </header>

      <div className="knowledge-chat-index" role="status">
        <span className={`knowledge-index-dot ${indexStatus?.ready ? 'ready' : ''}`} aria-hidden="true" />
        <strong>{indexStatus === null ? 'Checking knowledge index…' : indexStatus.ready ? 'Knowledge index ready' : 'Knowledge index needs setup'}</strong>
        {indexStatus && <span className="knowledge-chat-index-detail">{indexStatus.embedding_model ?? 'No embeddings'} · {indexStatus.source_count} sources · {indexStatus.chunk_count} chunks</span>}
        <button type="button" onClick={() => { void buildIndex() }} disabled={loading}>{loading ? 'Working…' : 'Build fixture index'}</button>
      </div>
      {(indexIsMock || buildReport) && <p className="knowledge-chat-note">{buildReport
        ? noIndexChanges
          ? `Index is current: ${buildReport.unchanged_sources.length} sources and ${buildReport.total_chunks} chunks reused.`
          : `Index updated: ${buildReport.added_sources.length} added · ${buildReport.updated_sources.length} updated · ${buildReport.acl_only_sources.length} ACL only · ${buildReport.removed_sources.length} removed · ${buildReport.embedded_chunks} chunks embedded.`
        : 'Mock vectors demonstrate retrieval wiring; they do not establish semantic search quality.'}</p>}
      {historyError && <p className="knowledge-chat-error" role="status">Saved chats: {historyError}</p>}
      {error && <p className="knowledge-chat-error" role="alert">{error}</p>}

      <div className="knowledge-chat-transcript" aria-live="polite" ref={transcriptRef}>
        {!transcriptQuestion && !loading && liveSteps.length === 0 && <div className="knowledge-chat-welcome">
          <span className="knowledge-chat-welcome-mark" aria-hidden="true">KB</span>
          <h3>What can I help you find?</h3>
          <p>Ask about a policy, process, or support case. I’ll answer from passages this persona is allowed to read.</p>
          <div className="knowledge-chat-suggestions" aria-label={`Suggested questions for ${personas.find((item) => item.persona_id === personaId)?.label ?? 'this role'}`}>
            {(ROLE_SUGGESTIONS[personaId] ?? ['How do I request time off?', 'What security steps should I follow?']).map((suggestion) => <button key={suggestion} type="button" disabled={loading || !indexStatus?.ready || !personaId} onClick={() => { void runAnswer(suggestion) }}>{suggestion}</button>)}
          </div>
        </div>}

        {previousTurns.map((previousTurn) => <PreviousKnowledgeTurn key={previousTurn.run_id} answer={previousTurn} />)}

        {transcriptQuestion && <article className="knowledge-chat-message user-message">
          <span className="knowledge-message-author">You</span>
          <p>{transcriptQuestion}</p>
        </article>}

        {(answer || loading || liveSteps.length > 0) && <article className="knowledge-chat-message assistant-message">
          <div className="knowledge-assistant-heading">
            <span className="knowledge-assistant-avatar" aria-hidden="true">KB</span>
            <strong>Knowledge assistant</strong>
            <span className={`knowledge-assistant-status ${loading ? 'is-running' : ''}`}>{answerView?.status ?? 'Working'}</span>
          </div>
          {loading && progressItems.length > 0 && <TaskScroll items={progressItems} active className="knowledge-chat-progress" />}
          {loading && !answer && <p className="knowledge-chat-thinking">Checking authorized sources and citations…</p>}
        {answer && <KnowledgeClaims answer={answer} />}
          {answer?.available_actions.includes('support_follow_up') && !answer.action_proposal && <section className="knowledge-follow-up-suggestion" aria-label="Suggested follow-up action">
            <div><strong>Need a next step?</strong><span>I can prepare a support follow-up from the cited ticket. You’ll review it before anything is created.</span></div>
            <button type="button" disabled={loading || !followUpEvidence} onClick={() => {
              if (followUpEvidence) void runAnswer(`Create a support follow-up based on the cited ticket “${followUpEvidence.title}”. Summarize the next step for the support team.`)
            }}>Prepare follow-up</button>
          </section>}
          {answer?.action_proposal && <section className="knowledge-action-proposal">
            <div className="knowledge-action-proposal-heading"><p className="section-kicker">Support follow-up</p><span className={`knowledge-action-status knowledge-action-status-${answer.action_status}`}>{answer.action_status === 'pending_approval' ? 'Awaiting approval' : answer.action_status?.replaceAll('_', ' ')}</span></div>
            <h4>{answer.action_proposal.title}</h4>
            <MarkdownContent>{answer.action_proposal.description}</MarkdownContent>
            <div className="knowledge-action-citations"><CitationBadges citations={answer.action_proposal.evidence_ids.flatMap((id) => answer.evidence.filter((item) => item.evidence_id === id))} /></div>
            <p className="knowledge-action-message">{answerView?.message}</p>
            {answer.action_status === 'pending_approval' && <div className="knowledge-action-approval">
              <label><span>Approver</span><select value={approverId} onChange={(event) => setApproverId(event.target.value)} disabled={loading}>{approvers.map((item) => <option key={item.approver_id} value={item.approver_id}>{item.label}</option>)}</select></label>
              <div className="knowledge-action-buttons"><button type="button" className="primary-button" disabled={loading} onClick={() => { void decideAction('approve') }}>Approve task</button><button type="button" className="knowledge-reject-button" disabled={loading} onClick={() => { void decideAction('reject') }}>Reject</button></div>
            </div>}
            {answer.mock_task && <p className="knowledge-run-meta" role="status">Created mock task {answer.mock_task.task_id} · {answer.mock_task.status} · {answer.mock_task.source_id}</p>}
            <p className="knowledge-run-meta">Demo approval only · no external task system</p>
          </section>}
          {answer && answer.claims.length === 0 && !answer.action_proposal && <p className="knowledge-answer-abstain">{answerView?.message}</p>}
          {answer && <div className="knowledge-answer-footer">{answer.fixture_version && <>Fixture {answer.fixture_version} · {answer.embedding_model} · </>}{answer.authorized_source_ids.length} authorized sources</div>}
        </article>}
      </div>

      <form className="knowledge-chat-composer" onSubmit={(event) => { event.preventDefault(); void runAnswer() }}>
        <label className="knowledge-chat-input-label" htmlFor="knowledge-question">Message the knowledge base</label>
        <textarea
          id="knowledge-question"
          value={question}
          maxLength={500}
          rows={2}
          placeholder="Ask a question about a policy, process, or support case…"
          onChange={(event) => { setQuestion(event.target.value) }}
          onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void runAnswer() } }}
        />
        <div className="knowledge-composer-footer">
          <span>Enter to send · Shift+Enter for a new line</span>
          <div>
            <button className="primary-button" type="submit" disabled={loading || !indexStatus?.ready || !personaId || !question.trim()}>{loading ? 'Working…' : 'Send'}</button>
          </div>
        </div>
      </form>
      <p className="knowledge-chat-disclaimer">Deterministic request checks run before Jev classification. Personas and approvers are simulated; mock task records stay in the local demo database.</p>
    </section>

    {(answer || liveSteps.length > 0) && <section className="knowledge-run-details" aria-label="Run details">
      <div className="knowledge-run-details-heading"><div><p className="section-kicker">Inspectable trace</p><h3>Workflow and verification</h3></div><span>{workflowSteps.length} steps</span></div>
      <details className="knowledge-answer-walkthrough" open={loading}>
        <summary>Workflow steps</summary>
        <ol>{workflowSteps.map((step) => <li key={step.sequence}>
          <strong>{step.sequence}. {step.stage.replaceAll('_', ' ')} · {step.status}</strong>
          <p>{step.summary}</p>
          <details><summary>Inputs and results</summary><pre>{JSON.stringify(step.details, null, 2)}</pre></details>
        </li>)}</ol>
      </details>
      {answer && <details className="knowledge-answer-walkthrough"><summary>Verification and usage</summary><pre>{JSON.stringify({ verification: answer.verification, usage: answer.usage }, null, 2)}</pre></details>}
    </section>}

    </>}
    </>
  )
}
