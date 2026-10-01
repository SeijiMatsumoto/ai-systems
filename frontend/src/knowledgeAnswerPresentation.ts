import type { KnowledgeAnswerResult, KnowledgeEvidence } from './types'

export interface KnowledgeClaimView {
  statement: string
  citations: KnowledgeEvidence[]
}

export function presentKnowledgeAnswer(answer: KnowledgeAnswerResult) {
  const status = answer.status === 'failed'
    ? 'Run failed'
    : answer.stop_reason === 'answered' ? 'Verified answer'
      : answer.action_status === 'pending_approval' ? 'Awaiting approval'
        : answer.action_status === 'executed' ? 'Mock task created'
          : answer.action_status === 'rejected' ? 'Proposal rejected'
            : answer.action_status === 'blocked' ? 'Action blocked' : 'Abstained'
  const title = answer.action_proposal
    ? 'Action proposal'
    : answer.stop_reason === 'answered'
      ? 'Answer'
      : answer.stop_reason.replaceAll('_', ' ')
  const messages: Record<string, string> = {
    read_only_action_request: 'That action is not supported. This demo can prepare only an approved support follow-up from authorized ticket evidence.',
    action_proposal_pending: 'Review the proposed support follow-up and approve or reject it below. No task exists yet.',
    action_proposal_rejected: 'The authorized approver rejected this proposal.',
    action_policy_blocked: 'Policy blocked the action because requester access, evidence, or source state did not pass checks.',
    action_approval_denied: 'This approver is not authorized for the proposed action. The proposal remains pending.',
    action_executed: 'The approved mock task was created. Repeated approval returns the same task.',
    action_proposal_error: 'The proposal model failed; no task was created.',
    action_intent_unavailable: 'The action intent check was unavailable, so no proposal was made.',
    no_relevant_passage: 'No authorized passage matched this question.',
    model_abstained: 'The answer model chose not to answer from the selected passages. Inspect the workflow to see what it received.',
    citation_rejected: 'The draft cited a passage that failed provenance checks.',
    grounding_rejected: 'The cited passage did not sufficiently support the claim.',
    grounding_unavailable: 'The grounding check was unavailable, so the answer was withheld.',
    answer_model_error: 'The answer model failed before a verified answer was available.',
    retrieval_error: 'Retrieval could not complete for this run.',
  }
  const claims: KnowledgeClaimView[] = answer.claims.map((claim) => ({
    statement: claim.statement,
    citations: claim.evidence_ids.flatMap((id) => {
      const evidence = answer.evidence.find((item) => item.evidence_id === id)
      return evidence ? [evidence] : []
    }),
  }))
  return { status, title, claims, message: messages[answer.stop_reason] ?? '', format: answer.answer_format }
}
