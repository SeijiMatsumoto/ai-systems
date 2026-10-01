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
| 3. Checked support actions | Confirmed pre-fulfillment cancellation/address-change proposals and human-review case creation for returns, warranty, damage, and refund requests | Committed as `3ce92d9` |
| 4. Reviewable demo experience | Chat UI, role/session selection, visible ordered workflow, saved conversation/run trace, and architecture diagram | UI implemented; awaiting review |

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

## Phase 4 UI - October 1, 2026

The user explicitly waived a separate phase plan and authorized implementing the UI with existing shared components and consistent system styling. Implemented simulated customer sign-in, per-customer browser-session retention, new/saved chats, server-owned conversation history, immediate suggestion/follow-up sends, Markdown, grouped citation tooltips, streamed task progress, exact pending-action cards, receipt-based disabled controls, human-review case cards, and external expandable workflow/usage details. The header architecture modal now explains source authority, prechecks/Jev, bounded agent loop, confirmation, human-review branches, and persistence. Extracted shared ArchitectureFlow nodes for Knowledge and Support.

Verification: frontend build and lint pass without warnings; 22 frontend tests pass, including split support SSE frames and failure/missing-completion cases. Rendered desktop/mobile browser checks with fake API responses cover sign-in, suggestions sending, input clearing, confirmation/receipt, case display, citation tooltip, loaded modal, new chat, and horizontal overflow. Explicit offline fixture ingestion created five local mock policy vectors. No live model/embedding calls or customer database writes occurred. Phase 4 remains uncommitted for review; real provider quality and a live end-to-end run remain unverified.

### Saved-run regression - provider usage serialization

Run `097cf4ae-4885-40e1-b2d2-346984df784b` classified “What are my orders?” as information (0.91), then failed with TypeError before logging the first model output. Real provider usage includes Decimal cost; the step JSON serializer accepted only primitive mock usage. Normalize adapter usage and workflow details with Pydantic's JSON conversion. Technical-failure cases now explicitly explain lookup failure rather than masking it as a normal review outcome. Added offline real RunUsage adapter coverage and an order-list plus five detail lookups with Decimal costs. All 62 support tests, Pyright, Ruff, and diff checks pass; no live provider call was used. Existing saved outcomes remain historical.

### Repeated order-list regression and customer/Admin split

Run `8fc4ce5b-a871-4f4f-bc61-f7469e22e354` classified the query correctly but called order_list seven times, exhausting the tool budget. The tool returned only uncitable identifiers. Order-list tools now return citable current snapshots excluding address/customer identity. Exact simple order-list phrases use validated deterministic owned reads and a template without Jev or model calls; ambiguous/general requests retain semantic classification. Identical repeated successful tool calls stop early with clarification. Offline regression verifies all five owned orders, zero model/Jev calls, and exclusion of foreign orders; realistic Decimal-usage coverage remains. All 63 support tests, Pyright/Ruff, 22 frontend tests, build/lint and diff checks pass. Rendered UI checks use fake APIs, with no provider calls.

Customer chat now shows simple progress, normal answers, policy/product sources, and action/case cards. Raw steps, usage, fixture diagnostics, and selectable message traces moved to a separate right-hand Admin view, stacking below on narrow screens. The previous Phase 4 note about details below the transcript is superseded. Changes remain uncommitted.

### Customer presentation polish

Aligned the chat/Admin cards by removing the inherited chat top margin within the two-column workspace. New review cases persist short ticket numbers scoped to the conversation in the existing JSON payload; opaque IDs remain internal. Older saved cases receive display aliases in chat. Customer text masks known opaque case references, and ticket cards use short labels and a concise support-follow-up message. Removed the unrelated generic refund/return/replacement warning from case answers/cards, including historical results rendered in the UI. No schema migration or provider call is required. Backend tests (63), Pyright/Ruff, frontend build/lint and mocked rendered interaction checks pass.

### Answer layouts

Order-list responses now use a four-column Markdown table: Order, Items, Payment, Delivery. Shared MarkdownContent supports GFM tables with contained horizontal scrolling, wrapping cells, and consistent headers. The support provider is instructed to use tables for comparisons/collections, numbered steps for procedures, bullets for short collections, and paragraphs for concise explanations; evidence checks still apply. Verified the real offline deterministic order-list output rendered as a five-row table in the chat, including contained mobile overflow. Backend suite (63), frontend tests (22), build/lint, Ruff and diff checks pass. No live model calls.

### Single-account customer experience

At the user's request, removed the identity picker and displayed customer name from Support. The page opens one demo account automatically, preserves saved chats in the browser session, and New chat directly starts a conversation. Order tables now show purchase dates instead of order IDs; customer text and action cards mask internal order references. Account-bound IDs and multi-customer isolation fixtures remain backend boundaries. Added 28px of space above the aligned chat/Admin workspace. Frontend build/lint and backend component checks pass; no live model calls. This supersedes earlier UI sign-in instructions.

### Transient persistence diagnostic

Investigated the reported persistence message: configured database reachable, all seven support tables present, session/chat/history/list repository probes passed in a rolled-back transaction, and running API conversation reads returned HTTP 200 before and after reload. The original failure was not reproduced; missing migrations were ruled out for the checked database. Enabled shared SQLAlchemy pool_pre_ping to check stale pooled connections before reuse. Support errors now distinguish missing-table SQLSTATE from temporary persistence failures, with safe class/SQLSTATE logging and customer-facing wording. Support suite (63), shared DB tests (3), Ruff/diff checks pass. No model calls or lasting probe records.

### Decision and source-loop repair - October 1, 2026

Diagnosed conversation `6112f398-81a8-4ca6-8246-bf3e2b26af35`, run `7fb451b6-92c8-455a-a9dc-1a3d4c924620`: the cancellation query produced a mixed tool/clarification wire response, had no output retries, and automatically created a general ticket on technical failure. Replaced the wire contract with a tagged DecisionEnvelope, one bounded validation repair, and preserved failed-attempt usage/diagnostics. Internal ModelTurn remains a validated normalization record. Technical failures no longer save cases automatically; explicit human requests and checked case proposals still do. Order evidence includes product names/types. Customer progress now says Thinking...

Authorized live smoke revealed repeated reads, including reworded policy searches. Source selection now closes on exact repeated reads, unchanged evidence, completed compatibility/case reads, current order plus policy reads, or the six-tool limit. FinalDecisionEnvelope excludes tools and asks the model to answer, propose, or clarify; ordinary citation/grounding/authorization checks remain. Clarification wire validation requires one question ending in a question mark; policy facts belong in cited answers. Jev uses separate positive AND negative criteria for factual answers, pending changes, and human-review cases. A reported refund request does not require proof of customer assertions or prior human approval to record a review case; execution remains absent.

Offline verification: 73 support tests, including actual PydanticAI FunctionModel schema/repair tests, duplicate/new-evidence boundaries, failed usage persistence without tickets, product identity, and separate review-case criteria. Frontend build/lint and 22 tests pass; Python type/Ruff/format and whitespace checks pass. FunctionModel and fake SDK tests do not prove live semantic quality.

Live allowance used conservatively: eight completed workflow attempts, one interrupted refund workflow, and one accidental adapter call caused by a stale test mock after moving run to iter. Corrected the mock and added an offline OpenAI request guard. Completed initial smoke results: order listing passed; eligibility exhausted tokens, cancellation/policy/compatibility repeated reads, and delivery classification was uncertain. After the source-loop fix, eligibility reached a clarification rejected for an appended explanation; refund reached a correctly targeted review proposal rejected by Jev at 0.59. The final clarification and Jev-criteria fixes were made afterward and remain live-unverified. Recorded support-model cost is at least $0.01534218, including the accidental call but excluding interrupted-run usage and Jev charges; completed workflow usage reports 67,171 input and 4,929 output tokens across providers. Full artifacts are /tmp/support-smoke.json and /tmp/support-smoke-retest.json. No database business records outside isolated SQLite or confirmed changes. Changes remain uncommitted.

### Saved-chat regression: uncertain intent blocking authorized reads

Chat `4296fd34-1598-4daf-a383-dc6e469f3d29`, run `7a401f1a-eb50-4cba-883a-4b870b408648`, asked “Can I cancel my unshipped camera order?”. Jev returned information at 0.68, below 0.8; the app stopped before any order/policy read with a generic clarification. Low confidence about information versus action now selects a bounded read-only route with operation proposals disabled. It can gather authoritative evidence and answer eligibility; uncertainty cannot create a case or pending action. Low-confidence human/unsupported classifications still clarify. The saved raw classification remains in the trace alongside the explicit route decision. Offline regression covers both information and action predictions at 0.68 with operations initially enabled. No new paid calls were made; final live behavior remains unverified.

### Reuse complete order snapshots

Saved chat `f68167ba-77f2-4fc6-b5a3-78a6e0613db5` used four support-model calls and three reads: order list, policy, then redundant order detail. The order list already includes complete owned snapshots and eligibility inputs. After that read the harness removes list/detail tools; when both order and policy evidence are available it switches to the existing final-decision schema. No query-specific answer is injected. The model still writes the cited answer, and provenance and Jev grounding still run; confirmation execution still rechecks fresh state. Offline regression exercises list→policy and policy→list, requiring only two reads and three model turns. Final decisions may clarify if evidence is insufficient. No new live provider calls were made.

### Follow-up cancellation evidence completion

Saved chat `083ea305-13de-4ea3-b0e1-6ce57000202e` correctly passed the previous R50 answer and order reference into “Yes, cancel please”; Jev classified action at 0.94. A repeated order lookup prematurely closed retrieval, then the proposal failed missing_policy_evidence. Duplicate-read handling now keeps a policy-only completion route available for action requests with current order evidence but no policy. Provider instructions explicitly require both current order and policy citations and use prior turns only for target resolution. An isolated API regression saves the first answer, submits the short follow-up, repeats the model's erroneous lookup, fetches policy, and saves a confirmation proposal without executing cancellation. No live calls made.

### Conversation smoke verification (October 1)

After 76 offline Customer Support tests passed, the user authorized verification against final code. Ran six sequential live messages across three isolated SQLite conversations via the streaming API: cancellation eligibility→“Yes, cancel please”, lens delivery→“Has it shipped yet?”, refund review→ticket status. All six reached expected outcomes. Checked the pending cancellation targets order-1001, refund case targets order-1004, delivery citations target order-1002, ticket citation matches the saved case, and no execution receipts exist. Live policy retrieval used the explicit mock index; these results do not establish embedding quality. Saved full outputs/steps/usage in `/tmp/support-conversation-smoke.json`. Times were 7.84, 7.51, 13.16, 6.89, 8.01, 5.54 seconds. Support-model reported cost totaled $0.00994130, excluding Jev charges. Cancellation follow-up now works in this live sample; six passes do not establish broad reliability. Remaining issue: delivery made a redundant order-detail read despite tools being removed from the prompt's available-tool map, then repeated that read (blocked) and repaired a grounding rejection. The wire schema still permits tool names absent from that map, so tool availability is not structurally enforced. This efficiency gap is explicitly unresolved. Frontend build/lint and all 22 tests passed; no rendered browser verification was performed in this pass. Changes remain uncommitted.

## Resumable support tasks — Phase 1

Approved scope: use the existing FastAPI, PostgreSQL and Pydantic AI stack; no LangGraph or workflow engine. Persist cancellation task checkpoints, associate execution outputs with tasks, resume explicit clarification/decision replies, and keep existing deterministic confirmation, state/version/policy checks and receipt idempotency. Ordinary policy/status questions remain message-driven. Broader semantic continuation routing and other task types are Phase 2; evidence caching and structural tool availability are Phase 3.

Implementation: `TaskCheckpoint` is a typed contract with goal, selected order references, waiting state, pending proposal/question, completed check stages, evidence run/IDs and checkpoint version. Migration 011 adds `support_tasks` and nullable `support_outputs.task_id`. The API loads/creates the task under the conversation reservation, supplies its saved target as non-authoritative context, and saves output/operation/checkpoint atomically. Confirmation/rejection also updates the same task. Waiting approval replies return instructions for the existing card without invoking providers or creating another proposal. Explicit different order IDs start a separate task. Phase 1 routing deliberately uses explicit cancellation and short replies, with exact order-ID replies accepted for clarification; this is routing context, not action authorization. No process remains alive while waiting. Task events are persisted and visible in Admin view and the architecture modal explains pause/resume.

Acceptance: isolated API tests reconstruct the repository and move the original answer outside the four-turn window, then verify that a cancellation follow-up resumes the same checkpoint, completes missing policy evidence, creates one confirmation proposal, ignores duplicate approval text for execution, and completes the same task through checked confirmation. Additional tests cover clarification resumption, unrelated questions and conversation isolation. Existing stale order/policy, ownership, concurrent confirmation, replay and rollback tests remain applicable. Pending: review and migration 011 on the configured database. No paid live run is part of this phase's routine verification; previous live results predate this change. This implements saved-checkpoint continuation, not recovery from arbitrary mid-model/process crashes.

Phase 1 verification: 78 Customer Support offline tests passed; the restart regression rebuilds both FastAPI/TestClient and the repository over the same isolated SQLite store. Pyright with `.venv/bin/python` reports zero errors. Ruff check/format and `git diff --check` pass. Frontend build/lint and 22 tests pass. No rendered browser or paid provider verification was performed. Migration 011 remains unapplied to the configured PostgreSQL database; apply it before exercising the task-enabled API.

### One authorized live resumption verification

At the user's “do it, just once” request, applied migration 011 transactionally to the configured demo PostgreSQL database using its direct connection; verified support_tasks columns and support_outputs.task_id. Ran one two-message cancellation conversation against real support/Jev providers and isolated SQLite records. Recreated FastAPI, repository, store and provider instances between eligibility and “Yes, cancel please” while retaining only the database and session/chat IDs. Both messages passed: first answered eligibility (9.57s), second resumed the identical saved task/target and persisted a cancellation confirmation proposal (13.16s). Checkpoint versions advanced 2→3, no action receipt was produced, and no cancellation/refund executed. Saved full results/steps/usage in `/tmp/support-resume-once.json`. This recreated application objects, not an actual OS process restart; offline checkpoints also cover transcript-window independence. Follow-up made one blocked duplicate order read before completing policy evidence; efficiency remains a Phase 3 concern. No retries or additional live conversations were run. This verifies one conversation only. Changes remain uncommitted.

### Efficiency follow-up

At the user's request, scoped output schemas now enumerate only currently available tool names, cached by the tool-name set. The real adapter uses this schema each turn; an offline FunctionModel regression verifies that unavailable order_detail is absent and an invalid selection uses the existing single schema repair. A deterministic availability check also prevents noncompliant/fake providers from executing removed tools. For a resumed cancellation task with one authorized saved target, the harness refreshes that current order directly before the first model turn, records the scoped read and eligibility facts, and removes order_detail from available choices. The model retrieves policy and then produces the verified proposal. A complete offline API regression verifies two model turns, two distinct reads and no duplicate lookup attempt, versus the four model turns in the preceding live sample. Current execution checks, Jev routing/grounding and confirmation remain intact. These efficiency changes have not been live-verified; no additional paid calls were made.

Efficiency verification: 81 offline tests pass, including a noncompliant-provider regression proving that an order-detail request after the complete order list is not executed. The older Decimal usage regression was corrected to answer from list snapshots instead of scripting five redundant detail reads. Pyright reports zero errors; Ruff and diff checks pass. No new live verification or commits.

## Resumable tasks — Phase 2

Approved scope: typed new/resume/correct/abandon/clarify routing, deterministic prechecks before Jev for ambiguous references, address-change and human-review task checkpoints, preserved tasks across topic switches, corrections/rejection/abandonment, and offline conversation verification. No new orchestration framework or database migration; migration 011's JSON checkpoints accommodate expanded contracts.

`task_routing.py` validates/normalizes the message and produces cheap topic/reference signals. Explicit owned task IDs (used by ticket follow-up buttons), a unique explicit topic and a short reply to the current single waiting task can route without another model. These routes select context only; intent, grounded proposals, ownership/state/policy and specific confirmation still control all actions. Ambiguous continuations use a bounded Jev decision over up to eight compact task candidates from the twenty most recent non-abandoned tasks in the owned chat. Semantic routing requires probability >=0.8 and a winner margin >=0.1. Unknown task IDs are rejected; ambiguity clarifies without modifying tasks. Routing usage is included in the execution token budget and saved output; precheck/input/decision steps appear before the agent steps with monotonically increasing sequence IDs.

Address changes and human-review cases now retain checkpoint types and saved case references. Verified operation proposals can create a task even when a cheap keyword signal missed the request. Completed review tasks support case-status continuations without reopening execution. A correction before approval clears old target/evidence/completed-work references so current evidence must be gathered again. Topic switches leave other checkpoints and proposals intact. Non-pending work can be abandoned; changing/abandoning a pending proposal asks for its explicit rejection card. Informational questions about a pending task can still be answered without creating another proposal. Routing timeouts save a failed run and preserve pending tasks, without creating a case or retrying a paid call.

Offline tests cover topic switching and returning to an older task, ambiguous multiple targets, corrected targets, abandonment, explicit rejection, address-change task state, human-review case follow-ups, low confidence, close semantic ties, unknown/foreign task identifiers, routing input bounds/order and routing timeout. Provider requests are mocked; no live Phase 2 calls or rendered browser checks were made. Phase 2 implementation was reviewed and approved for commit. Live semantic routing quality remains unverified.

Phase 2 verification: 94 Customer Support offline tests passed; Pyright reports zero errors. Ruff check and format check, frontend build/lint and 22 frontend tests, and `git diff --check` pass. No live provider calls or rendered browser verification were performed for this phase.

Review follow-ups: confirmation cards identify products, quantities, order date and item total from exact-order evidence; missing details disable confirmation. Customer cards omit redundant source/status/introduction copy and space CTA controls. Clear action continuations such as “Do it for me” resume the current single waiting task and direct to the existing confirmation card without paid classification or execution. Added routing variants and an API regression. Final offline suite: 95 backend tests; 24 frontend tests. Frontend build/lint and Ruff/diff checks passed after relevant edits. User UI testing exercised cancellation continuity and prompted this regression; broader live routing quality remains unverified.
