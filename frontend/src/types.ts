export type ResearchRunStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface KnowledgeStep {
  sequence: number
  stage: string
  status: 'running' | 'completed' | 'failed' | 'skipped'
  summary: string
  details: Record<string, unknown>
}

export interface KnowledgeEvidence {
  evidence_id: string
  chunk_id: string
  title: string
  excerpt: string
  locator: { source_id: string; revision: string; start: number; end: number }
}

export interface KnowledgeAnswerResult {
  run_id: string
  status: 'completed' | 'failed'
  stop_reason: string
  request: { persona_id: string; question: string; run_id: string | null }
  fixture_version: string | null
  embedding_model: string | null
  authorized_source_ids: string[]
  evidence: KnowledgeEvidence[]
  claims: Array<{ statement: string; evidence_ids: string[] }>
  available_actions: Array<'support_follow_up'>
  action_evidence_ids: string[]
  answer_format: 'paragraph' | 'bullet_list' | 'numbered_list'
  action_status: 'pending_approval' | 'rejected' | 'blocked' | 'executed' | null
  action_proposal: null | {
    task_type: 'support_follow_up'
    title: string
    description: string
    evidence_ids: string[]
    requester_persona_id: string
    idempotency_key: string
  }
  mock_task: null | { task_id: string; task_type: 'support_follow_up'; title: string; description: string; source_id: string; idempotency_key: string; status: 'open'; created_at: string }
  verification: Array<{ claim_index: number; passed: boolean; reason: string; judgment: { probability: number; model: string } | null }>
  steps: KnowledgeStep[]
  usage: Record<string, unknown>
  error_type: string | null
}

export interface KnowledgeApprover {
  approver_id: string
  label: string
  role: string
  allowed_action_types: string[]
}

export interface KnowledgeAnswerSummary {
  run_id: string
  status: 'completed' | 'failed'
  stop_reason: string
  persona_id: string
  question: string
  created_at: string
}

export interface BriefingRequest {
  symbol: string
  as_of: string
  research_question: string
  audience: string
  time_horizon: string
}

interface EvidenceBase {
  evidence_id: string
  reference_id: string
  title: string
  url: string | null
  retrieved_at: string
  published_at: string | null
}

export interface DocumentEvidence extends EvidenceBase {
  evidence_type: 'document'
  document_type: 'generic' | 'filing' | 'article'
  content_quality: 'full_text' | 'snippet'
  document_id: string
  chunk_id: string
  chunk_index: number
  start_char: number
  end_char: number
  content_hash: string
  quote: string
}

export interface FinancialEvidence extends EvidenceBase {
  evidence_type: 'financial'
  source: string
  field_path: string
  value: string | number | boolean | null
  period_end?: string | null
}

/** Version-1 payload retained so saved runs remain viewable. */
export interface LegacyEvidenceItem {
  evidence_type: 'financial' | 'document'
  source: string
  reference_id: string
  title: string
  url: string
  content: string | number
  retrieved_at: string
  published_at: string | null
  chunk_id: string | null
  chunk_index: number | null
  field_path: string | null
}

export type EvidenceItem = DocumentEvidence | FinancialEvidence | LegacyEvidenceItem

export interface Finding {
  statement: string
  claim_type: 'fact' | 'calculation' | 'inference' | 'scenario'
  confidence: number
  evidence: EvidenceItem[]
}

export interface ResearchBriefing {
  executive_summary: string
  key_findings: Finding[]
  outlook: string
  limitations: string[]
}

export interface GroundingFailure {
  finding_index: number
  reason: string
}

export interface VerificationResult {
  unsupported_finding_indexes: number[]
  invalid_evidence_references: string[]
  grounding_failures: GroundingFailure[]
  approval_ready: boolean
}

export interface ResearchWorkflowResult {
  run_id: string
  status: ResearchRunStatus
  briefing: ResearchBriefing | null
  verification: VerificationResult | null
}

export interface ResearchWorkflowStep {
  run_id: string
  sequence: number
  stage: 'run' | 'scope' | 'classifier' | 'prefetch' | 'agent' | 'tool' | 'verification' | 'checkpoint' | 'persistence'
  status: 'running' | 'completed' | 'failed' | 'skipped'
  summary: string
  details: Record<string, unknown>
  recorded_at: string
}

export interface ResearchRunDetail {
  run_id: string
  resumed_from_run_id: string | null
  symbol: string
  as_of: string
  status: ResearchRunStatus
  request_payload: BriefingRequest
  briefing_payload: ResearchBriefing | null
  verification_payload: VerificationResult | null
  usage_payload: Record<string, unknown>
  error_payload: Record<string, unknown> | null
  checkpoint_stage: string | null
  checkpoint_payload: Record<string, unknown> | null
  trace_id: string | null
  model_name: string
  prompt_version: string
  tool_version: string
  schema_version: string
  created_at: string
  started_at: string | null
  completed_at: string | null
  workflow_steps: ResearchWorkflowStep[]
}

export interface ResearchRunSummary {
  run_id: string
  symbol: string
  status: ResearchRunStatus
  research_question: string
  approval_ready: boolean | null
  created_at: string
  completed_at: string | null
}

export interface BackfillRequest {
  symbol: string
  as_of: string
  include_8k: boolean
}

export interface BackfillResult {
  symbol: string
  status: 'completed' | 'partial'
  total_documents_processed: number
  failures: number
  filings: Array<Record<string, unknown>>
}

export interface InvestigationRequest {
  service: string
  alert_id: string
  window_start: string
  window_end: string
}

export interface IncidentClaim {
  statement: string
  kind: 'fact' | 'correlation' | 'hypothesis'
  evidence_ids: string[]
}

export interface IncidentCoverageGap {
  source: 'log' | 'metric' | 'trace' | 'change'
  service: string
  start: string
  end: string
  reason: string
}

export interface IncidentEvidence {
  evidence_id: string
  source: 'log' | 'metric' | 'trace' | 'change' | 'alert'
  service: string
  locator: string
  observed_at: string
  excerpt: string
}

export interface IncidentReport {
  timeline: IncidentClaim[]
  likely_causes: IncidentClaim[]
  unknowns: string[]
  next_checks: string[]
  coverage_gaps: IncidentCoverageGap[]
  evidence: IncidentEvidence[]
  review_required: boolean
}

export interface IncidentReportReview {
  decision: 'approved' | 'changes_requested'
  note: string
  reviewed_at: string
}

export interface IncidentVerificationIssue {
  code: 'empty_report' | 'invalid_kind' | 'unknown_evidence' | 'not_surfaced' | 'outside_scope'
  path: string
  evidence_id: string | null
}

export interface IncidentVerification {
  passed: boolean
  issues: IncidentVerificationIssue[]
}

export interface IncidentToolStep {
  sequence: number
  tool_name: string
  arguments: Record<string, unknown>
  result: Record<string, unknown>
  returned_evidence_ids: string[]
  truncated: boolean
  condensed: boolean
  coverage_gaps: IncidentCoverageGap[]
  error: string | null
  duration_ms: number
}

export interface IncidentWorkflowStep {
  sequence: number
  stage: 'replay' | 'guardrail' | 'classifier' | 'scope' | 'registry' | 'agent' | 'tool' | 'verification'
  status: 'completed' | 'failed' | 'running'
  summary: string
  details: Record<string, unknown>
  elapsed_ms: number
}

export interface InvestigationResult {
  run_id: string
  status: 'completed' | 'failed'
  stop_reason: 'completed' | 'timeout' | 'budget_exhausted' | 'agent_error' | 'verification_failed'
  report: IncidentReport | null
  verification: IncidentVerification | null
  tool_steps: IncidentToolStep[]
  workflow_steps: IncidentWorkflowStep[]
  logfire_trace_id: string | null
  usage: Record<string, unknown>
  error_type: string | null
}

export interface DetectedIncident {
  incident_id: string
  cluster_id: string
  trigger_log_id: string
  service: string
  observed_at: string
  window_start: string
  window_end: string
}

export interface IncidentCandidateSummary {
  cluster_id: string
  trigger_log_id: string
  trigger_service: string
  observed_at: string
  services: string[]
  distinct_error_requests_last_5m: number
  log_levels: Record<string, number>
  representative_messages: string[]
  log_evidence_ids: string[]
  latest_error_rates: Record<string, number>
  metric_evidence_ids: string[]
}

export interface IncidentClassification {
  summary: IncidentCandidateSummary
  outcome: 'incident' | 'not_incident' | 'needs_review' | 'classifier_unavailable'
  judgment: {
    model: string
    question_version: number
    probability: number
    usage: Record<string, number>
  } | null
  error_type: string | null
}

export interface IncidentSimulationResult {
  run_id: string
  status: 'completed' | 'failed'
  stop_reason: string
  max_reports: number
  classifications: IncidentClassification[]
  detected_incidents: DetectedIncident[]
  investigations: InvestigationResult[]
  workflow_steps: IncidentWorkflowStep[]
  logfire_trace_id: string | null
  error_type: string | null
  review_decisions?: Record<string, IncidentReportReview>
}

export interface IncidentSimulationSummary {
  run_id: string
  status: 'completed' | 'failed'
  stop_reason: string
  report_count: number
  created_at: string
}

export interface DemoPersona {
  persona_id: string
  label: string
  groups: string[]
}

export interface RankedKnowledgeExcerpt {
  chunk_id: string
  title: string
  kind: string
  excerpt: string
  locator: { source_id: string; revision: string; start: number; end: number }
  lexical_rank: number | null
  vector_rank: number | null
  rerank_score: number
}

export interface KnowledgeCandidateTrace {
  chunk_id: string
  source_id: string
  rank: number
  score: number
}

export interface KnowledgeIndexStatus {
  ready: boolean
  fixture_version: string
  embedding_model: string | null
  source_count: number
  chunk_count: number
}

export interface KnowledgeIndexBuildReport {
  fixture_version: string
  embedding_model: string
  added_sources: string[]
  updated_sources: string[]
  unchanged_sources: string[]
  removed_sources: string[]
  acl_only_sources: string[]
  embedded_chunks: number
  total_chunks: number
}

export interface KnowledgeRetrievalPreview {
  fixture_version: string
  embedding_model: string
  persona_id: string
  normalized_question: string
  keyword_signals: string[]
  authorized_source_ids: string[]
  lexical_candidates: KnowledgeCandidateTrace[]
  vector_candidates: KnowledgeCandidateTrace[]
  ranked_excerpts: RankedKnowledgeExcerpt[]
  steps: { stage: string; detail: string; source_ids: string[] }[]
  stop_reason: 'retrieval_preview_only'
}
