export interface SupportCustomer { customer_id: string; display_name: string }
export interface SupportStep { sequence: number; stage: string; details: Record<string, unknown> }
export interface SupportEvidence { evidence_id: string; kind: string; source_id: string; locator: string; text: string }
export interface SupportAction {
  proposal_id: string; kind: 'cancel_order' | 'change_address'; order_id: string
  address: { line1: string; city: string; postal_code: string; country: string } | null
  state: 'pending' | 'confirmed' | 'rejected' | 'blocked'; expected_order_version: number
}
export interface SupportCase { ticket_number?: number | null; case_id: string; category: string; order_id: string | null; customer_statement: string; status: 'pending_review'; human_decision: 'not_decided' }
export interface SupportResult {
  run_id: string; conversation_id: string; disposition: string; answer: string; stop_reason: string
  pending_action: SupportAction | null; review_case: SupportCase | null
  receipt: { proposal_id: string; order_id: string; outcome: string; reason: string; order_version: number; refund_executed: false; case_id: string | null } | null
  evidence: SupportEvidence[]; steps: SupportStep[]; usage: Record<string, unknown>; embedding_model: string | null; fixture_version: string
}
export interface SupportTurn { question: string; response: SupportResult }
export interface SupportConversation { conversation_id: string; created_at: string; busy: boolean }
