import { useEffect, useRef, useState } from 'react'

import { buildKnowledgeMockIndex, getKnowledgeIndexStatus, getKnowledgePersonas, previewKnowledgeRetrieval } from './api'
import type { DemoPersona, KnowledgeIndexBuildReport, KnowledgeIndexStatus, KnowledgeRetrievalPreview } from './types'

export default function KnowledgeRetrievalPreview() {
  const [personas, setPersonas] = useState<DemoPersona[]>([])
  const [personaId, setPersonaId] = useState('')
  const [question, setQuestion] = useState('How do I request time off?')
  const [preview, setPreview] = useState<KnowledgeRetrievalPreview | null>(null)
  const [indexStatus, setIndexStatus] = useState<KnowledgeIndexStatus | null>(null)
  const [buildReport, setBuildReport] = useState<KnowledgeIndexBuildReport | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const requestSequence = useRef(0)

  useEffect(() => {
    let active = true
    Promise.all([getKnowledgePersonas(), getKnowledgeIndexStatus()]).then(([items, status]) => {
      if (!active) return
      setPersonas(items)
      setPersonaId(items[0]?.persona_id ?? '')
      setIndexStatus(status)
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Could not load demo personas')
    })
    return () => { active = false }
  }, [])

  const reset = () => {
    requestSequence.current += 1
    setPreview(null)
    setError('')
    setLoading(false)
  }

  const runPreview = async () => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setError('')
    setPreview(null)
    try {
      const result = await previewKnowledgeRetrieval(personaId, question)
      if (sequence === requestSequence.current) setPreview(result)
    } catch (cause) {
      if (sequence === requestSequence.current) setError(cause instanceof Error ? cause.message : 'Preview failed')
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
    <section className="knowledge-preview" aria-label="Access-filtered retrieval preview">
      <div className="knowledge-preview-intro">
        <p className="section-kicker">Phase 1 · ingestion + retrieval</p>
        <h2>Inspect the retrieval boundary</h2>
        <p>Ingest the synthetic corpus into citable chunks, then compare keyword and vector candidates within a simulated employee’s access scope.</p>
      </div>
      <div className="knowledge-index-status">
        <strong>{indexStatus?.ready ? 'Index ready' : 'Index not ready'}</strong>
        <span>{indexStatus?.embedding_model ?? 'No embeddings'} · {indexStatus?.source_count ?? 0} sources · {indexStatus?.chunk_count ?? 0} chunks</span>
        <button type="button" onClick={() => { void buildIndex() }} disabled={loading}>Build mock fixture index</button>
      </div>
      <p className="knowledge-preview-meta">Mock vectors exercise the architecture; they do not establish semantic retrieval quality. An OpenAI embedding adapter is available through the explicit ingestion command.</p>
      {buildReport && <p className="knowledge-preview-meta">Ingestion: {buildReport.added_sources.length} added · {buildReport.updated_sources.length} updated · {buildReport.acl_only_sources.length} ACL only · {buildReport.embedded_chunks} chunks embedded</p>}
      <form onSubmit={(event) => { event.preventDefault(); void runPreview() }}>
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
        <button className="primary-button" disabled={loading || !indexStatus?.ready || !personaId || !question.trim()} type="submit">
          {loading ? 'Checking access…' : 'Preview retrieval'}
        </button>
      </form>
      {error && <p className="knowledge-preview-error" role="alert">{error}</p>}
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
