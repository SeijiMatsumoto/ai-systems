import { useEffect, useRef, useState } from 'react'

import { buildKnowledgeMockIndex, getKnowledgeAnswer, getKnowledgeAnswers, getKnowledgeIndexStatus, getKnowledgePersonas, previewKnowledgeRetrieval, streamKnowledgeAnswer } from './api'
import { CitationTooltip } from './components/CitationTooltip'
import type { DemoPersona, KnowledgeAnswerResult, KnowledgeAnswerSummary, KnowledgeIndexBuildReport, KnowledgeIndexStatus, KnowledgeRetrievalPreview, KnowledgeStep } from './types'
import { presentKnowledgeAnswer } from './knowledgeAnswerPresentation'

function setRunUrl(runId: string | null) {
  const url = new URL(window.location.href)
  if (runId) url.searchParams.set('run', runId)
  else url.searchParams.delete('run')
  window.history.replaceState({}, '', url)
}

export default function KnowledgeRetrievalPreview() {
  const [personas, setPersonas] = useState<DemoPersona[]>([])
  const [personaId, setPersonaId] = useState('')
  const [question, setQuestion] = useState('How do I request time off?')
  const [preview, setPreview] = useState<KnowledgeRetrievalPreview | null>(null)
  const [answer, setAnswer] = useState<KnowledgeAnswerResult | null>(null)
  const [liveSteps, setLiveSteps] = useState<KnowledgeStep[]>([])
  const [savedAnswers, setSavedAnswers] = useState<KnowledgeAnswerSummary[]>([])
  const [historyError, setHistoryError] = useState('')
  const [indexStatus, setIndexStatus] = useState<KnowledgeIndexStatus | null>(null)
  const [buildReport, setBuildReport] = useState<KnowledgeIndexBuildReport | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const requestSequence = useRef(0)
  const answerView = answer ? presentKnowledgeAnswer(answer) : null
  const indexIsMock = indexStatus?.embedding_model === 'mock-embedding-v1'
  const noIndexChanges = buildReport && !buildReport.added_sources.length && !buildReport.updated_sources.length && !buildReport.removed_sources.length && !buildReport.acl_only_sources.length

  useEffect(() => {
    let active = true
    Promise.all([getKnowledgePersonas(), getKnowledgeIndexStatus()]).then(([items, status]) => {
      if (!active) return
      setPersonas(items)
      setPersonaId((current) => current || items[0]?.persona_id || '')
      setIndexStatus(status)
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
      setPersonaId(saved.request.persona_id)
      setQuestion(saved.request.question)
    }).catch((cause: unknown) => {
      if (active) setHistoryError(cause instanceof Error ? cause.message : 'Could not open saved answer')
    })
    return () => { active = false }
  }, [])

  const reset = () => {
    requestSequence.current += 1
    setPreview(null)
    setAnswer(null)
    setLiveSteps([])
    setRunUrl(null)
    setError('')
    setLoading(false)
  }

  const runPreview = async () => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError('')
    setPreview(null)
    setAnswer(null)
    setLiveSteps([])
    setRunUrl(null)
    try {
      const result = await previewKnowledgeRetrieval(personaId, question)
      if (sequence === requestSequence.current) setPreview(result)
    } catch (cause) {
      if (sequence === requestSequence.current) setError(cause instanceof Error ? cause.message : 'Preview failed')
    } finally {
      if (sequence === requestSequence.current) setLoading(false)
    }
  }

  const runAnswer = async () => {
    const sequence = ++requestSequence.current
    const runId = crypto.randomUUID()
    setLoading(true)
    setError('')
    setAnswer(null)
    setPreview(null)
    setLiveSteps([])
    setRunUrl(runId)
    try {
      const completed = await streamKnowledgeAnswer(personaId, question, runId, (step) => {
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
      setLiveSteps([])
      setPreview(null)
      setPersonaId(saved.request.persona_id)
      setQuestion(saved.request.question)
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
    setPreview(null)
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

  return (
    <section className="knowledge-preview" aria-label="Access-filtered knowledge assistant">
      <div className="knowledge-preview-intro">
        <p className="section-kicker">Phase 2 · cited read-only answers</p>
        <h2>Ask the knowledge base</h2>
        <p>Answers use only passages this demo persona can read. Open the workflow to inspect retrieval, model context, citation checks, and Jev grounding.</p>
      </div>
      <div className="knowledge-index-status">
        <strong>{indexStatus === null ? 'Checking index…' : indexStatus.ready ? 'Index ready' : 'Index not ready'}</strong>
        {indexStatus && <span>{indexStatus.embedding_model ?? 'No embeddings'} · {indexStatus.source_count} sources · {indexStatus.chunk_count} chunks indexed</span>}
        <button type="button" onClick={() => { void buildIndex() }} disabled={loading}>Build mock fixture index</button>
      </div>
      {indexIsMock && <p className="knowledge-preview-meta">This index uses mock vectors to demonstrate retrieval. They do not establish semantic search quality. The OpenAI embedding adapter is available through the explicit ingestion command.</p>}
      {buildReport && <p className="knowledge-preview-meta" role="status">{noIndexChanges
        ? `Index already up to date: ${buildReport.unchanged_sources.length} sources and ${buildReport.total_chunks} chunks reused; no new embeddings needed.`
        : `Index updated: ${buildReport.added_sources.length} added · ${buildReport.updated_sources.length} updated · ${buildReport.acl_only_sources.length} ACL only · ${buildReport.removed_sources.length} removed · ${buildReport.embedded_chunks} new chunks embedded · ${buildReport.total_chunks} total chunks.`}</p>}
      <form onSubmit={(event) => { event.preventDefault(); void runAnswer() }}>
        <label>
          <span>Demo persona</span>
          <select value={personaId} onChange={(event) => { reset(); setPersonaId(event.target.value) }} disabled={!personas.length}>
            {personas.map((item) => <option key={item.persona_id} value={item.persona_id}>{item.label}</option>)}
          </select>
        </label>
        <label>
          <span>Question</span>
          <input value={question} maxLength={500} onChange={(event) => { reset(); setQuestion(event.target.value) }} />
        </label>
        <div className="knowledge-form-actions">
          <button className="primary-button" disabled={loading || !indexStatus?.ready || !personaId || !question.trim()} type="submit">
            {loading ? 'Running…' : 'Answer with citations'}
          </button>
          <button type="button" disabled={loading || !indexStatus?.ready || !personaId || !question.trim()} onClick={() => { void runPreview() }}>Inspect retrieval only</button>
        </div>
      </form>
      <p className="knowledge-preview-meta">Answering calls the configured answer model and Jev. Retrieval-only inspection uses mock vectors when the mock index is selected.</p>
      {savedAnswers.length > 0 && <label className="knowledge-history">
        <span>Saved answers</span>
        <select value={answer?.run_id ?? ''} onChange={(event) => { if (event.target.value) void selectSavedAnswer(event.target.value) }} disabled={loading}>
          <option value="">Select a run</option>
          {savedAnswers.map((item) => <option key={item.run_id} value={item.run_id}>{new Date(item.created_at).toLocaleString()} · {item.question} · {item.stop_reason.replaceAll('_', ' ')}</option>)}
        </select>
      </label>}
      {historyError && <p className="knowledge-preview-meta" role="status">Saved history: {historyError}</p>}
      {error && <p className="knowledge-preview-error" role="alert">{error}</p>}
      {(answer || liveSteps.length > 0) && <div className="knowledge-answer-result">
        <div className="knowledge-answer-header">
          <p className="section-kicker">{answerView?.status ?? 'Working'}</p>
          <h3>{answerView?.title ?? 'Checking sources and citations…'}</h3>
          {answer?.error_type && <p>Recorded error: {answer.error_type}</p>}
        </div>
        {answerView?.claims.length ? <div className="knowledge-answer-claim">
          <p>{answerView.claims.map((claim, index) => <span key={`${index}-${claim.statement}`}>
            {index > 0 && ' '}{claim.statement}
            <span className="knowledge-answer-citations">{claim.citations.map((item) => <CitationTooltip
              key={item.evidence_id}
              className="knowledge-citation-chip"
              label={`${item.title} · ${item.evidence_id}`}
              sourceTitle={item.title}
              excerpt={item.excerpt}
              metadata={[
                { value: `${item.locator.source_id}@${item.locator.revision}:${item.locator.start}-${item.locator.end}`, code: true },
                { label: 'Chunk', value: item.chunk_id, code: true },
              ]}
            />)}</span>
          </span>)}</p>
        </div> : null}
        {answer && answer.claims.length === 0 && <p className="knowledge-answer-abstain">{answerView?.message}</p>}
        {answer && <p className="knowledge-preview-meta">Fixture {answer.fixture_version ?? '—'} · {answer.embedding_model ?? '—'} · {answer.authorized_source_ids.length} authorized sources</p>}
        <details className="knowledge-answer-walkthrough" open={loading}>
          <summary>Workflow · {(answer?.steps ?? liveSteps).length} steps</summary>
          <ol>{(answer?.steps ?? liveSteps).map((step) => <li key={step.sequence}>
            <strong>{step.sequence}. {step.stage.replaceAll('_', ' ')} · {step.status}</strong>
            <p>{step.summary}</p>
            <details><summary>Inputs and results</summary><pre>{JSON.stringify(step.details, null, 2)}</pre></details>
          </li>)}</ol>
        </details>
        {answer && <details className="knowledge-answer-walkthrough"><summary>Verification and usage</summary><pre>{JSON.stringify({ verification: answer.verification, usage: answer.usage }, null, 2)}</pre></details>}
      </div>}
      {preview && <div className="knowledge-preview-result">
        <p className="knowledge-preview-meta">Fixture {preview.fixture_version} · {preview.embedding_model} · {preview.stop_reason.replaceAll('_', ' ')}</p>
        <ol className="knowledge-preview-steps">
          {preview.steps.map((step) => <li key={step.stage}>
            <strong>{step.stage.replaceAll('_', ' ')}</strong>
            <p>{step.detail}</p>
            {step.source_ids.length > 0 && <code>{step.source_ids.join(' · ')}</code>}
          </li>)}
        </ol>
        <div className="knowledge-candidates">
          <div><h3>Keyword candidates</h3>{preview.lexical_candidates.length ? preview.lexical_candidates.map((item) => <code key={item.chunk_id}>{item.rank}. {item.chunk_id} · {item.score.toFixed(3)}</code>) : <p>No candidates</p>}</div>
          <div><h3>Vector candidates</h3>{preview.vector_candidates.length ? preview.vector_candidates.map((item) => <code key={item.chunk_id}>{item.rank}. {item.chunk_id} · {item.score.toFixed(3)}</code>) : <p>No candidates</p>}</div>
        </div>
        <h3>Ranked authorized excerpts</h3>
        {preview.ranked_excerpts.length === 0 && <p>No authorized source matched this question. This preview does not generate an answer.</p>}
        {preview.ranked_excerpts.map((item) => <article className="knowledge-preview-source" key={item.chunk_id}>
          <div><strong>{item.title}</strong><span>{item.kind} · keyword #{item.lexical_rank ?? '—'} · vector #{item.vector_rank ?? '—'}</span></div>
          <blockquote>{item.excerpt}</blockquote>
          <code>{item.locator.source_id}@{item.locator.revision}:{item.locator.start}-{item.locator.end}</code>
        </article>)}
      </div>}
    </section>
  )
}
