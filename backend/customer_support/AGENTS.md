# Customer Support implementation plan

## Product and safety boundaries

This demo represents customer support for a fictional camera-equipment retailer. Use recognizable camera bodies and lenses for compatibility examples, grounded in manufacturer-published compatibility information. Customers, orders, addresses, and support cases are synthetic.

The architecture must keep retailer policy separate from authoritative customer, order, fulfillment, and catalog state. A simulated signed-in identity is resolved by the server; a request body or model output must never select another customer. The assistant may explain policy, look up order status, and perform bounded read-only lens compatibility checks. It may request a pre-fulfillment cancellation or address change through a checked action flow. Return, warranty, damage, and refund requests create a case for human review. The AI must never issue or promise a refund.

Before every LLM or Jev call, run deterministic input validation, normalization, bounds, and cheap keyword/pattern checks. Use those checks to reject clearly invalid requests or supply signals for classification, not as semantic proof. Apply deterministic authorization, state, policy, and output checks after model decisions. Keep all external writes and real customer/payment data out of this demo.

## Whole-system architecture requirements

Follow section 4 of the Notion Top 5 AI System Designs outline. The completed demo has separate policy hybrid retrieval/reranking, authoritative customer/order/catalog reads, and checked action tools under one bounded orchestrator. Carry the server-resolved identity into every scoped tool call. Dynamic order state stays outside the knowledge index.

Conversation context, traces, and evaluations are cross-cutting requirements from Phase 2 onward, not deferred UI features: use compact recent turns plus structured references, shared `llm_runs`, ordered persisted tool arguments/results and check outcomes, provider-reported usage, loop limits, and explicit stop reasons. Grounding/confidence and deterministic policy checks decide answer versus escalation. Escalation covers human requests, unsupported operations, ambiguity, low confidence, and repeated failures. Checked actions require confirmation, authorization, execution-time state rechecks, and idempotency. The final UI presents these saved facts; it does not invent model private reasoning.

## Phase roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1. Domain and mock store foundation | Typed domain contracts, synthetic catalog/order/policy fixtures, and scoped deterministic store adapter | Reviewed; uncommitted |
| 2. Read-only support answers | Request prechecks, bounded intent classification, policy/account/catalog tools, grounded response and citation verification | Plan awaiting review |
| 3. Checked support actions | Confirmed pre-fulfillment cancellation/address-change proposals and human-review case creation for returns, warranty, damage, and refund requests | Not started |
| 4. Reviewable demo experience | Chat UI, role/session selection, visible ordered workflow, saved conversation/run trace, and architecture diagram | Not started |

## Phase 1 plan: domain and mock store foundation

### Goal

Create a deterministic, testable source-of-truth boundary that later model-driven work can call without letting a model invent customer state, policy, product compatibility, or permissions.

### Proposed changes

1. **Typed contracts in `contracts.py`**
   - Define validated records for the simulated principal, support request scope, product and mount data, lens compatibility result, order and order line, fulfillment/address state, policy document/locator, and store lookup outcomes.
   - Use explicit enums for order/fulfillment states and compatibility outcomes (`compatible`, `incompatible`, `unknown`); unknown must not be presented as compatible.
   - Keep the authenticated/simulated principal separate from the user message and any model-generated arguments. Keep policy evidence separate from account/order facts.
   - Bound identifiers and free-text fields and reject malformed or oversized values at the request boundary.

2. **Versioned synthetic fixtures**
   - Add small, human-readable fixtures under `backend/customer_support/fixtures/` for catalog/compatibility, synthetic customers and orders, and support policies.
   - Include multiple recognizable camera bodies and lenses with mount compatibility grounded in manufacturer sources; record source URLs and retrieval/check date alongside those facts.
   - Include synthetic orders that exercise paid but unfulfilled, label-created, shipped, and delivered states, plus return-window and warranty examples. Include cancellation/address-change eligibility facts without performing those actions.
   - Include policy passages and stable locators for cancellation, address correction, returns, warranty/damage claims, and refund review. State that any refund decision belongs to a human reviewer.
   - Validate fixture references and uniqueness at load time. No real people, orders, addresses, or support transcripts.

3. **Deterministic store adapter in `store.py`**
   - Provide narrow read methods for the current principal's orders, order details, catalog products, lens compatibility, and policy passages.
   - Scope order reads inside the adapter using the server-resolved principal. Cross-customer lookups return a non-revealing not-found result.
   - Return typed results with stable record IDs and source locators. Do not let the adapter infer policy from order state or infer order state from policy text.
   - Keep this phase read-only. Later phases can add a support-specific persistence boundary for cases and approved mock actions.

4. **Focused offline tests**
   - Test contract validation, fixture integrity, state-specific order lookups, cross-customer isolation, policy/catalog separation, and compatibility outcomes including unknown mount combinations.
   - Test missing or malformed fixtures fail clearly rather than silently yielding empty or permissive results.
   - Use only local fixtures and fake dependencies; make no LLM, Jev, network, payment, or external task-system calls.

### Acceptance criteria

- A deterministic caller can retrieve policy, catalog/compatibility, and only the active synthetic customer's order data through separate typed methods.
- A caller cannot retrieve another customer's order by changing an order ID or supplying a customer ID in the message/request payload.
- Compatibility is explicit and conservative: unsupported or incomplete combinations return `unknown`.
- Fixtures state the provenance of compatibility facts and use no real customer or transaction data.
- The focused customer-support unit tests, Ruff checks, and `git diff --check` pass.

### Out of scope for Phase 1

No LLM/Jev classification, chat endpoint or UI, conversation persistence, action execution, case creation, real integrations, or changes to other systems. Refund processing is excluded from the entire demo; later action work may create only a human-review case.

### Phase 1 review gate

Phase 1 implementation is complete and uncommitted, awaiting user review. Fourteen offline tests passed, covering strict request/lookup arguments, fixture references and dates, cross-customer isolation, order states, separate policy/account reads, known/unknown compatibility, evidence requirements, and missing/malformed fixtures. Incompatible-result behavior uses a modified test fixture; catalog assertions only contain manufacturer-established pairings. Ruff checks and formatting were applied. No LLM/Jev calls were made. Tavily search/extraction was used once to establish manufacturer provenance, outside routine tests.

Wait for implementation review and explicit commit approval before committing; wait for review before planning or starting Phase 2.

## Phase 2 plan: read-only support conversation backend

Phase 1 review was accepted by the user's instruction to move to Phase 2. Phase 1 changes remain uncommitted; that instruction does not authorize a commit. Phase 2 details await review.

### Goal and request flow

Build a backend conversation slice that answers policy, order-status, and catalog/compatibility questions using separate evidence tools. Preserve customer context across turns, validate grounding, and produce an explicit answer, clarification, or handoff-needed outcome.

```text
Server-owned demo session -> owned conversation + recent context
 -> deterministic request validation / keyword signals
 -> Jev intent judgment -> deterministic routing thresholds
 -> bounded support model / read-only tools
     policy hybrid retrieval + reranking
     current customer-bound order lookup
     catalog / exact compatibility lookup
 -> deterministic output/citation checks
 -> Jev grounding judgment -> deterministic acceptance threshold
 -> saved answer / clarification / handoff-needed + ordered steps
```

### Technical changes

1. **Structured policy contracts and fixtures.** Add typed policy rules for return-window days, retailer warranty-review days, permitted cancellation/address-change fulfillment states, and a literal prohibition on AI refund execution. Store their values in versioned fixture data. Generate corresponding rule descriptions from those values so prose and executable values cannot diverge. Preserve explanatory passages and exact locators for retrieval. This phase can explain eligibility but never execute actions; later execution must re-read state and rules.
2. **Policy ingestion and retrieval.** Index policy passages with lexical and embedding representations; use hybrid retrieval, bounded rank fusion/reranking, and context limits. Reuse the existing knowledge embedding/retrieval primitives where appropriate without sharing its corpus or ACL semantics. Real embeddings require an explicit ingestion command; fake vectors are for offline tests and must be labeled if selected at runtime. Missing or mismatched indexes return an explained unavailable result, never silently substitute mock vectors. Customer orders remain in the scoped store, outside the policy index.
3. **Conversation and session boundary.** Add a server-owned simulated session mapped to one fixture customer. Persist conversations and messages scoped to that session/customer; reject cross-customer conversation access. Accept a bounded message with no client-selected customer identity. Assemble bounded recent relevant turns plus structured product/order references; resolve ambiguity by asking a question. Prior messages remain untrusted context, and prior order observations require fresh lookup before current-state claims.
4. **Prechecks and Jev routing.** Normalize and validate messages, identifier references, context lengths, and scope before calling Jev. Record keyword signals for order status, policy, compatibility, cancellation/address change, refund/return/warranty, and human requests. Jev handles ambiguous intent; deterministic thresholds choose the branch. Requests for unavailable actions or human assistance produce `handoff_needed` or clarification. Do not invent a case ID or imply that a human has received a case in Phase 2.
5. **Bounded read-only tool orchestration.** Define strict schemas for policy search, owned-order list/detail, catalog lookup, and compatibility lookup. Bind identity outside model arguments. Use a single bounded model loop with explicit tool/turn/context limits, typed tool failures, and visible stop reasons. Give the model only retrieved evidence and scoped observations; record its visible decisions, tool arguments, and results. Reuse existing model/provider and Jev adapters without introducing another agent framework.
6. **Grounded output contracts and verification.** Return one Markdown answer with grouped citations to exact policy passages, catalog provenance, or scoped order fields. Freeze the run evidence catalog as observations arrive. Validate citation IDs, locators, field values, scope, output length, and prohibited refund/action claims before Jev grounding. Apply a deterministic grounding threshold; allow at most one bounded repair, then clarify or return `handoff_needed` on unresolved evidence. Private model reasoning is unavailable.
7. **API, saved runs, and diagnostics.** Add Customer Support routes for demo sessions, conversations, messages, and owned history; register the router in `backend/main.py`. Use shared `llm_runs` plus support-specific conversation/output tables and a numbered migration. Save ordered checks, model/tool inputs and outputs, evidence, provider-reported usage, failure outcomes, and stop reasons. Expose progress events for the later chat UI. No frontend changes in this phase.
8. **Component and workflow evaluations.** Fake all model/embedding/Jev dependencies in routine verification. Cover policy retrieval, order ownership, follow-up reference resolution, fresh order reads, tool argument validation, budgets, grounding thresholds, missing indexes, provider failures, unsupported actions/refunds, and explicit human requests. Exercise API ownership, persistence, and progress event ordering. Run a complete mocked multi-tool conversation with realistic provider usage plus at least one failure workflow.

### Acceptance criteria

- Policy, order status, and established camera/lens compatibility questions produce verified evidence-backed answers through the correct tools.
- Follow-ups use the same owned conversation, resolve relevant references, and retrieve current order state again.
- Missing evidence, uncertain compatibility, low confidence, and failures produce an explicit clarification or handoff-needed result.
- Cancellation, address changes, returns, and refunds cannot execute, and no case ID is invented.
- Every model/Jev call has preceding deterministic checks and recorded post-response validation/threshold decisions.
- Saved results preserve ordered steps, scoped evidence, usage, and stop reasons; API history enforces conversation ownership.
- Offline component and multi-tool workflow checks, applicable database tests, Ruff, and `git diff --check` pass. Report any unexercised database boundary explicitly. No live LLM calls during verification.

### Review gate

Implement only after review of this Phase 2 plan. Present uncommitted changes and verification results for review before starting Phase 3 or committing.
