import { useState } from 'react'

import { incidentReviewSummary } from './incidentReviewSummary'
import type { DetectedIncident, IncidentReport, IncidentReportReview } from './types'

export default function IncidentReviewStage({
  report,
  detected,
  reportId,
  review,
  onDecision,
}: {
  report: IncidentReport
  detected: DetectedIncident
  reportId: string
  review: IncidentReportReview | undefined
  onDecision: (decision: 'approved' | 'changes_requested', note: string) => Promise<void>
}) {
  const [showChanges, setShowChanges] = useState(false)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const brief = incidentReviewSummary(report, detected)
  const status = review?.decision ?? 'pending'

  const submit = async (decision: 'approved' | 'changes_requested') => {
    setSaving(true)
    setError(null)
    try {
      await onDecision(decision, decision === 'approved' ? '' : note.trim())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the review decision.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={`incident-approval incident-approval-${status}`} aria-labelledby={`incident-approval-title-${reportId}`}>
      <div className="incident-approval-heading">
        <div>
          <p className="section-kicker">Decision brief / {detected.service} / {new Date(detected.observed_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })} UTC</p>
          <h2 id={`incident-approval-title-${reportId}`}>What happened, and what likely caused it</h2>
        </div>
        <span className="incident-approval-status">{review ? review.decision.replace('_', ' ') : 'Pending approval'}</span>
      </div>

      <div className="incident-approval-core">
        <div className="incident-approval-core-item">
          <span>Trigger / observed impact</span>
          <p>{brief.trigger}</p>
          <small>{brief.triggerEvidenceIds.join(' · ')}</small>
        </div>
        <div className="incident-approval-core-item">
          <span>Proposed cause / hypothesis</span>
          <p>{brief.cause}</p>
          <small>{brief.causeEvidenceIds.length ? brief.causeEvidenceIds.join(' · ') : 'No cited cause proposed'}</small>
        </div>
      </div>

      <div className="incident-approval-context">
        <div>
          <strong>Why the hypothesis is plausible</strong>
          {brief.supporting.length ? (
            <ul>{brief.supporting.map((item, index) => <li key={`${item.evidenceIds.join('-')}-${index}`}>{item.statement}</li>)}</ul>
          ) : <p>No additional supporting observation was listed.</p>}
        </div>
        <div>
          <strong>Still unconfirmed</strong>
          <p>{brief.keyUnknown}</p>
          {report.unknowns.length > 1 && <small>+ {report.unknowns.length - 1} more unknowns in the full report</small>}
        </div>
      </div>

      <div className="incident-approval-decision">
        <div>
          <span>Engineer decision</span>
          <strong>{review ? review.decision === 'approved' ? 'Draft approved' : 'Revision requested' : 'Is this draft ready to accept?'}</strong>
          <p>{review
            ? 'This decision is saved with the simulation. The proposed cause remains a hypothesis.'
            : 'Approve the accuracy of this cited summary and its stated uncertainty. Approval does not confirm root cause or authorize mitigation.'}</p>
          {review && <small>Recorded {new Date(review.reviewed_at).toLocaleString()}{review.note ? ` · ${review.note}` : ''}</small>}
        </div>
        {!review && (
          <div className="incident-approval-actions">
            <button type="button" className="incident-approval-approve" disabled={saving} onClick={() => void submit('approved')}>Approve draft</button>
            <button type="button" className="incident-approval-request" disabled={saving} aria-expanded={showChanges} onClick={() => setShowChanges((open) => !open)}>Request changes</button>
          </div>
        )}
      </div>
      {!review && showChanges && (
        <div className="incident-approval-feedback">
          <label htmlFor={`incident-approval-note-${reportId}`}>What needs to change?</label>
          <textarea id={`incident-approval-note-${reportId}`} value={note} maxLength={500} rows={3} onChange={(event) => setNote(event.target.value)} placeholder="Identify an unsupported claim, missing evidence, or an unresolved check." />
          <button type="button" disabled={saving || !note.trim()} onClick={() => void submit('changes_requested')}>{saving ? 'Saving…' : 'Save change request'}</button>
        </div>
      )}
      {error && <p className="incident-approval-error" role="alert">{error}</p>}
      <p className="incident-approval-footnote">Demo decision with no reviewer identity. It is final for this saved report and triggers no remediation.</p>
    </section>
  )
}
