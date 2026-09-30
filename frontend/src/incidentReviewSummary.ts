import type { DetectedIncident, IncidentClaim, IncidentReport } from './types'

function statement(claim: IncidentClaim | undefined): string | null {
  return claim?.statement.replace(/^(Fact|Correlation|Hypothesis):\s*/i, '').trim() || null
}

export function incidentReviewSummary(report: IncidentReport, detected: DetectedIncident) {
  const triggerClaim = report.timeline.find((claim) =>
    claim.kind === 'fact' && claim.evidence_ids.includes(detected.trigger_log_id),
  ) ?? report.timeline.find((claim) =>
    claim.kind === 'fact' && claim.evidence_ids.some((id) =>
      report.evidence.some((item) => item.evidence_id === id && item.source === 'log'),
    ),
  )
  const triggerRecord = report.evidence.find((item) => item.evidence_id === detected.trigger_log_id)
  const supporting = report.timeline
    .filter((claim) => claim !== triggerClaim)
    .slice(0, 3)
    .map((claim) => ({ statement: statement(claim) ?? claim.statement, evidenceIds: claim.evidence_ids }))
  const cause = report.likely_causes[0]

  return {
    trigger: statement(triggerClaim) ?? triggerRecord?.excerpt ?? `An error in ${detected.service} crossed the candidate threshold.`,
    triggerEvidenceIds: triggerClaim?.evidence_ids ?? [detected.trigger_log_id],
    cause: statement(cause) ?? 'The investigator did not identify a supported candidate cause.',
    causeEvidenceIds: cause?.evidence_ids ?? [],
    supporting,
    keyUnknown: report.unknowns[0] ?? 'No unresolved question was listed in the draft.',
  }
}
