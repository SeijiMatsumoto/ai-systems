export type ResearchRunStatus = 'pending' | 'running' | 'completed' | 'failed'

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

export interface ResearchRunDetail {
  run_id: string
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
  stage: 'scope' | 'registry' | 'agent' | 'tool' | 'verification'
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
