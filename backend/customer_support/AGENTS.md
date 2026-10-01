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
| 1. Domain and mock store foundation | Typed domain contracts, synthetic catalog/order/policy fixtures, and scoped deterministic store adapter | Committed as `5f82918` |
| 2. Read-only support answers | Request prechecks, bounded intent classification, policy/account/catalog tools, grounded response and citation verification | Committed as `585b19a` |
| 3. Checked support actions | Confirmed pre-fulfillment cancellation/address-change proposals and human-review case creation for returns, warranty, damage, and refund requests | Reviewed and approved for commit |
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

Phase 1 implementation was reviewed and committed as `5f82918` before Phase 2 started. Fourteen offline tests passed, covering strict request/lookup arguments, fixture references and dates, cross-customer isolation, order states, separate policy/account reads, known/unknown compatibility, evidence requirements, and missing/malformed fixtures. Incompatible-result behavior uses a modified test fixture; catalog assertions only contain manufacturer-established pairings. Ruff checks and formatting were applied. No LLM/Jev calls were made. Tavily search/extraction was used once to establish manufacturer provenance, outside routine tests.

Phase 1 review and commit gates were satisfied by the user.

## Phase 2 plan: read-only support conversation backend

The user approved this Phase 2 plan and requested committing Phase 1 first. Phase 1 was committed as `5f82918`; Phase 2 implementation was reviewed and approved for commit.

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

Phase 2 implementation was reviewed and approved for commit. Verification: 41 support offline tests, 35 existing Knowledge tests, and 3 shared run-registry tests passed. Support checks exercise strict inputs, typed policy rules and exact window boundaries, hybrid retrieval, index mismatch/missing/dimension failures, model and Jev adapter shapes, multi-tool evidence and usage, owned API persistence, follow-up context/fresh reads, one repair, confidence branches, numeric/action claim rejection, tool/token limits, and streamed provider failure/terminal persistence. Providers are fake; persistence uses isolated SQLite tables. Ruff and diff checks are required before review.

Migration 009 is supplied but has not been applied to the configured PostgreSQL database; actual PostgreSQL migration execution and live OpenAI/Jev/embedding behavior remain unverified. No frontend changes or case/action execution are included. The Phase 2 review and commit gates are satisfied. Phase 3 was subsequently approved.

## Phase 3 plan: checked mock actions and human-review cases

Phase 2 was committed as `585b19a`. The user approved this detailed plan. Phase 3 is implemented, reviewed, and approved for commit; no Phase 4 runtime work has started.

### Goal

Extend the existing conversation backend to support confirmed pre-fulfillment cancellations and address corrections, and to save human-review cases for returns, refunds, warranty/damage claims, and support escalation. The AI cannot issue refunds, approve returns, promise replacements, or decide human-review cases.

### Request flow

```text
Owned conversation -> deterministic prechecks -> Jev intent + thresholds
 -> scoped policy/order reads -> typed action or case proposal
 -> deterministic ownership/schema/state/rule/evidence checks
 -> Jev judges proposal support -> application acceptance threshold
     cancellation/address change -> saved pending proposal
        -> explicit confirmation -> fresh state/rule/version checks
        -> atomic mock update + receipt + saved steps
     return/refund/warranty/damage/human request -> saved human-review case
        -> real local case ID + pending-review status
```

### Technical changes

1. **Action and case contracts.** Define explicit enums and discriminated schemas in `contracts.py` for cancellation, address correction, human-review case categories, proposal states, confirmation decisions, and execution receipts. Return structured pending proposals and saved case/receipt references alongside the existing Markdown answer. Bind customer, conversation, run, and idempotency identifiers in application code. Never accept model-selected ownership, execution status, or case IDs.
2. **Persistent mock order state.** Add support-specific local order records initialized idempotently from the synthetic fixture. Read order state through the same customer-scoped adapter boundary; use the database record as the source of truth after seeding. Include a version for conditional updates. Restarting the backend or signing in again must preserve a cancelled order or corrected address. Catalog and policy fixtures remain versioned source data, and orders remain outside the embedding index. Add migration 010 for orders, proposals, execution receipts, and cases.
3. **Proposal generation within the current harness.** Extend the existing bounded single-agent output/tool contracts for action proposals and case requests. Reuse policy/order retrieval and the existing step/usage/evidence catalog. Missing order references, an incomplete replacement address, ambiguous intent, or unsupported operations produce a clarification. Deterministic proposal validation precedes Jev semantic support judgment; application thresholds then accept or decline the proposal. Keep customer-reported symptoms/reasons distinguishable from verified order/policy facts.
4. **Confirmed cancellation and address correction.** Require a paid, unfulfilled, customer-owned order under the structured policy rules. Show the exact order and requested change in a persisted pending proposal. A typed confirmation endpoint approves or rejects that specific proposal; reading a suggestion or producing model text cannot execute it. On confirmation, re-read identity, order state/version, and current rules. Atomically apply the mock update and save a receipt. If the order state or proposal is stale, reject with an explained result rather than silently changing the proposed action. Cancellation never invokes a payment or refund tool.
5. **Human-review cases.** Persist cases for return/refund review, warranty/damage claims, explicit human requests, unsupported actions, policy ambiguity, and unresolved failures. Attach only owned order references, relevant verified evidence, recent relevant conversation context, and clearly labeled customer statements. Generate the case ID in the application/database and return it only after successful persistence. State `pending_review` and explicitly describe what a human must decide. Requests outside return/warranty review windows still become cases; they are not automatically approved or denied. General support escalation may omit an order, while an order-specific case needs a resolved owned order.
6. **Idempotency and ownership.** Give each proposal/case operation a server-issued stable idempotency key. Enforce unique keys and one terminal execution per proposal in the database. Repeated confirmations return the saved receipt; concurrent or conflicting confirmations cannot execute twice. Equivalent retries of one operation reuse its case ID. A new conversational request is a new operation; do not accidentally merge distinct customer issues. Confirmation and case history endpoints enforce session/conversation ownership.
7. **Saved decisions and follow-ups.** Persist proposal checks, confirmation/rejection, execution-time rechecks, conditional updates, case creation, receipts, and explicit stop reasons in the existing ordered run history. Decision operations use shared `llm_runs` with links to the original proposal run. Subsequent messages can resolve the current pending proposal or saved case from structured conversation references. Allow customers to ask for their case status; the demo reports saved local state without inventing a human resolution or external ticket integration.
8. **Offline component and workflow tests.** Verify strict schemas, scoped seeded orders, persistence across sessions, proposal grounding/thresholds, missing details, stale state/rules, cross-customer access, confirmation/rejection, idempotent retries, conflicting decisions, and rollback if receipt/case persistence fails. Exercise complete mocked workflows for cancellation, address correction, refund case creation, outside-window review, and a failure/handoff. Confirm follow-ups read updated order state or the saved case. Test API and streaming/history payloads, provider usage, and ordered checks without live model calls.

### Acceptance criteria

- An eligible cancellation or address correction waits for explicit confirmation, applies exactly once, and returns a saved receipt.
- A shipped/label-created order or stale proposal cannot be automatically changed; the result explains the check and offers/routes human review.
- Refund, return, warranty/damage, and general escalation requests receive a saved case ID and `pending_review`, without any refund, approval, or replacement promise.
- Missing details prompt a targeted clarification before an order-specific case or action is accepted.
- Follow-ups see the persisted latest order/proposal/case state; changing sessions or restarting does not reset mutations.
- Customer identity and operation identifiers remain application-owned; another customer cannot read, confirm, or modify these records.
- Offline component, transaction, API, and mocked multi-step workflow checks pass, plus relevant shared regression tests, Ruff, and `git diff --check`.

### Scope and review gate

This phase implements backend mock state and actions only. The chat interface, confirmation cards, citation tooltips, and architecture modal update belong to Phase 4. No payment/refund executor, external ticketing/carrier writes, simulated human resolution, or live LLM calls are included. Report PostgreSQL migration execution separately from isolated offline ORM tests. After approval, implement Phase 3 alone and present the uncommitted changes for review before starting Phase 4 or committing.

## Phase 3 verification and review

Implemented strict action/case contracts, persistent seeded orders, grounded proposals, explicit confirmation/rejection, fresh state/rule/version checks, atomic receipts and case persistence, owned case follow-ups, and safe saved-run replay. API progress includes persistence and final stop only after successful commit. Refund execution is absent.

Offline verification: 60 Customer Support tests, 35 Knowledge tests, and 3 shared run-registry tests; fake model/Jev/embedding providers and isolated SQLite. Coverage includes multi-tool workflows, stale state/policy, rejected/invented proposals, cross-customer isolation, outside-window refund review, case follow-ups, repeated/conflicting/concurrent confirmations, and persistence rollback. Support Pyright, Ruff and diff whitespace checks pass. No live provider requests, frontend changes, or configured PostgreSQL migrations were performed. PostgreSQL execution/concurrency and live model quality remain unverified. The user reviewed Phase 3 and authorized its commit; Phase 4 requires its own detailed approved plan.

### Configured database migration verification - October 1, 2026

At the user's request, applied migrations 009 and 010 together in one transaction over a direct connection to the app's configured PostgreSQL database. Confirmed the shared `llm_runs` prerequisite and absence of support tables before applying. Verified all seven support tables, exact ORM column names, foreign-key targets, unique proposal/case idempotency keys, and unique receipt proposal IDs after commit. No customer records were seeded or changed, and no provider calls were made. This supersedes the earlier unapplied-migration notes; PostgreSQL end-to-end workflows/concurrency and live provider quality remain unverified.
