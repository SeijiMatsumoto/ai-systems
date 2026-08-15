export type ResearchRunStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface BriefingRequest {
  symbol: string
  as_of: string
  research_question: string
  audience: string
  time_horizon: string
}

export interface EvidenceItem {
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
  company_name: string
  from_date: string
  as_of: string
  include_filings: boolean
  include_news: boolean
  include_8k: boolean
}

export interface BackfillResult {
  symbol: string
  company_name: string
  status: 'completed' | 'partial'
  total_documents_processed: number
  failures: number
  filings: Array<Record<string, unknown>>
  news: Array<Record<string, unknown>>
}
