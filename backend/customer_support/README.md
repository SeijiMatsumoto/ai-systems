# Customer Support Agent

The runnable camera-shop demo separates policy, current account facts, conversational subjects, and checked action tasks. Synthetic orders and local cases support grounded answers and confirmed mock cancellation/address changes. Live language quality remains unverified; offline providers test application boundaries.

## Architecture

The demo separates policy retrieval, authoritative account/order reads, and checked action tools. Camera equipment makes the examples concrete. The backend flow is:

```text
Simulated sign-in -> conversation API + compact conversation state
  -> deterministic request checks -> Jev classification + application thresholds
  -> bounded orchestrator
       policy hybrid retrieval + reranking -> cited policy evidence
       scoped order/catalog tools -> current structured facts
       action proposal -> schema/auth/state/policy checks -> confirmation
  -> grounded answer verification / confidence and policy gate
  -> customer answer, checked mock action, or saved human-review case

Across every branch: llm_runs identity, ordered saved steps, budgets,
provider usage, explicit stop reasons, offline component/workflow evaluations.
```

Conversation state holds recent relevant turns and structured references, and never replaces current order reads. Escalation handles explicit human requests, ambiguity, unsupported requests, low confidence, and repeated tool failures. Mutations require idempotency and state rechecks. Refunds always become human-review cases; the AI never issues or promises them.

## Phase 1 foundation

- `contracts.py`: strict, immutable domain records and bounded lookup arguments. `SupportRequest` excludes customer identity; extra fields are rejected.
- `fixtures/store_v1.json`: two synthetic customers, seven orders, five Canon camera/lens catalog records, three established camera/lens pairings, and five fictional retailer policies.
- `store.py`: read-only catalog/policy/compatibility methods and customer-bound order methods. Foreign and missing orders produce the same not-found result.
- `tests/test_store.py`: offline component coverage for inputs, fixture integrity, isolation, states, provenance requirements, and failure cases.

The fixture uses a fixed scenario date of October 1, 2026. Prices, addresses, customer names, retailer terms, and transactions are fictional. Canon pairings were checked using Tavily search/extraction of Canon's official announcement; each established pairing stores the URL, locator, and check date. The catalog is deliberately small: absent pairings return `unknown`, even where a broader real-world compatibility rule might apply. Adapter support and individual camera features are outside this lookup. Incompatible-result behavior is exercised with a test fixture; no unsupported incompatibility claim is published in the catalog.

Customer/catalog/policy fixtures remain immutable; orders seed into persistent mock records and subsequent reads use database state. `PolicyRules` stores return-window days, warranty-review days, permitted fulfillment states, and the refund prohibition. Policy templates render their values from these fields; `review_order` uses the same fields to compute read-only window/state eligibility. These results are not action authorization or return/refund approval.

`retrieval.py` explicitly ingests only policy passages, then combines BM25-style lexical scoring with vector similarity, reciprocal-rank fusion, and a bounded deterministic rerank. It returns at most three passages. Missing or mismatched indexes fail explicitly; the runtime never silently creates mock embeddings. Mock vectors demonstrate this boundary and do not establish semantic retrieval quality.

Simulated sign-in creates an opaque server-owned session token for a fixture customer. This is demo identity selection, not authentication for real users. Order tool arguments and message payloads cannot supply another customer ID. Conversations are scoped to their session token; order lookups are scoped to the session's customer.

## Phase 2 flow and limits

`providers.py` defines the bounded support-model and Jev adapters. `service.py` validates and records keyword signals before Jev classification, applies a probability threshold, and runs a single model loop with read-only tools. Each model call has context/token checks; every tool call has strict argument validation. Current order details are read again for follow-ups. Order observations include product names/types to distinguish camera bodies from lenses and resolve purchase dates. Up to four prior turns are included, with bounded text and owned order/product references; prior assistant answers are never evidence.

The loop permits eight model turns, six tool executions, a 20,000 reported-token budget, a 120-second deadline, one schema repair per model decision, and at most one grounding repair for an answer. `DecisionEnvelope` tags tool, answer, clarification, or proposal; mixed branches receive bounded validation feedback. A separate `FinalDecisionEnvelope` excludes tools when completed reads repeat, add no evidence, reach the tool limit, or provide an exact compatibility/case result. Cancellation/address reads close source selection after current order and policy reads. The agent then answers, proposes, or clarifies from the collected facts. Failed attempts retain reported usage and validation diagnostics. Individual provider requests have timeouts; support-model responses are capped at 1,600 output tokens. The token budget checks provider-reported usage and constrains later requests; it is not an exact pre-billing cost guarantee.

Answers contain Markdown paragraphs or lists and grouped exact citations. Deterministic checks reject unknown evidence IDs, unsupported numeric/order references, and obvious execution/refund claims before Jev judges semantic grounding. The application accepts grounding only at probability 0.8 or above. Citation checks establish provenance, not semantic truth; fake-provider tests do not prove live grounding quality. Clarification text receives deterministic checks too.

Missing action details produce a clarification. Explicit human requests and verified case proposals save human-review cases. Unsupported requests clarify scope. Technical failures, unavailable tools, and exhausted budgets do not automatically create tickets; they save an explainable failed or incomplete outcome. Order-specific return/refund/warranty/damage proposals save owned cases with application-generated IDs and pending-review status. Customer statements remain labeled unverified; no human resolution is simulated. `repository.py` stores conversations and complete run outputs under shared `llm_runs`, with ordered steps, evidence, provider usage, and stop reasons. One active run per conversation prevents interleaved messages; interruption saves a failed outcome and releases the reservation. Process-crash recovery is not implemented.

## Phase 3 actions and cases

Typed model proposals cannot execute changes. Schema, ownership, evidence, customer-statement/address checks, and current rule/state signals precede Jev proposal grounding. Accepted cancellation/address proposals are persisted as pending. The confirmation endpoint rechecks ownership, order version, state, and the policy fingerprint before an atomic conditional update, receipt, saved output, and shared run completion. Only paid, unfulfilled orders qualify. Rejection leaves the order unchanged; stale or ineligible changes route to a review case. Cancellation never calls a payment/refund service.

Stable server-issued operation keys and unique receipts prevent duplicate execution. Replaying a saved run returns its committed result without repeating model calls or case creation; a new message is a new operation. Failed persistence rolls back the case/change and releases the conversation reservation. Concurrent confirmation coverage uses SQLite; PostgreSQL schema was verified after migration; PostgreSQL concurrency behavior remains unverified.

Cases hold the exact customer statement, owned order references, verified evidence, and bounded recent context. All remain `pending_review` with financial resolution `not_decided`. Refunds, returns, warranty and damage claims are human decisions, including requests outside policy windows. No external ticket, carrier, or payment integration exists.

## Setup

Apply `backend/db/migrations/009_create_support_conversations.sql` followed by `010_create_support_actions.sql`, `011_create_support_tasks.sql` and `012_support_conversation_context.sql` to an existing configured PostgreSQL database after migration 004. New database initialization includes the ORM tables. Migrations 009 and 010 were applied together to this checkout's configured database on October 1, 2026. All seven tables, ORM column names, foreign keys, and idempotency constraints were verified. Offline persistence tests use isolated SQLite tables.

Explicit policy ingestion:

```sh
# Offline fixture vectors; clearly labeled by the saved embedding model.
.venv/bin/python -m backend.customer_support.retrieval --provider mock

# Live embedding call; run only when intentionally enabling real embeddings.
.venv/bin/python -m backend.customer_support.retrieval --provider openai
```

The index defaults to ignored `backend/customer_support/.data/policy_index.json`; use `--index-path` and `SUPPORT_POLICY_INDEX` to select another path. Real answer and query adapters use the existing backend OpenAI/Jev environment configuration. No live LLM or embedding request was run during Phase 2 verification.

The API prefix is `/agent/customer_support`:

- `GET /customers`: synthetic sign-in choices.
- `POST /sessions`: `{ "customer_id": "customer-alex" }` returns a demo token.
- `POST /conversations` and `GET /conversations`: create/list owned chats.
- `GET /conversations/{id}`: owned saved messages/results, including steps.
- `POST /conversations/{id}/messages`: `{ "message": "Where is order-1001?" }` returns a verified response or explained stop.
- `POST /conversations/{id}/proposals/{proposal_id}/decision`: `{ "decision": "confirm" }` or `reject`, returning a saved receipt or blocked result.
- `GET /conversations/{id}/cases` and `/cases/{case_id}`: owned saved review cases.
- `POST /conversations/{id}/runs/{run_id}/replay`: retrieve a committed operation result safely.
- `POST /conversations/{id}/messages/stream`: the same payload, with SSE `started`, ordered `step`, and persisted `completed` events; heartbeat comments keep the stream active.

Conversation routes require `Authorization: Bearer <demo token>`. Backend routing is registered in `backend/main.py`; the frontend Support page connects these routes.

## Run offline checks

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/customer_support/tests -v
```

No provider calls or external writes occur in these tests. Detailed phase scope and review gates are in `AGENTS.md`.

## Customer chat UI

Open Customer Support from the workspace; the chat opens automatically for one demo account, with no login form or displayed identity. Suggested questions send immediately; Enter sends and Shift+Enter adds a line. Sources appear once after the answer using the shared citation tooltip. Confirm/reject controls apply to a specific persisted proposal; saved receipts disable completed controls. Case status buttons send a follow-up message.

New chat immediately creates a fresh conversation. The demo session token is retained in sessionStorage, so saved chats are available within the same browser tab/session. Only the conversation reference is in the URL; IDs are not shown in the header. Full workflow details and usage appear in a separate Admin view to the right (below on narrow screens); the customer chat shows simple progress. Exact order-list requests render current owned records directly without model calls; broader requests use the bounded agent. The shared header architecture button opens the support diagram.

Phase 4 uses shared CitationTooltip, MarkdownContent, TaskScroll/taskTrail, ArchitectureModal, and architecture stage nodes. Policy fixtures were explicitly ingested with mock vectors locally; quality remains unverified. Build/lint and 22 frontend tests pass, including support SSE failure/partial-frame coverage. Rendered desktop/mobile checks used fake API responses for sign-in, suggestion submission, clearing input, confirmation/receipt, case display, tooltip/modal, new-chat reset, and viewport overflow. No live LLM or embedding calls were made.

## Explicit live smoke

After the offline gate, with authorization for paid calls:

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m backend.customer_support.support_smoke --live --limit 9
```

Varied prompts exercise real support/Jev providers, streaming, saved conversations, proposals, review cases, and a ticket follow-up. Records use isolated in-memory SQLite and the existing explicitly ingested mock policy vectors. No proposal is confirmed. Full results and usage save to `/tmp/support-smoke.json`; this command is excluded from unittest discovery.

## Conversation context and action tasks

Each chat persists a versioned context: ordered subjects, an unresolved question with ordered choices, and checked policy passages. This survives repository recreation and history truncation. Old chats initialize conservatively from a single cited subject; an old multi-order answer does not pick an arbitrary order.

After input and ownership checks, Jev classifies intent once. Its typed input contains the current message, bounded recent dialogue, ordered subjects/pending choices and keyword signals. Task goals, tool schemas and cached evidence are excluded. All categories share a rubric for current conversational intent; eligibility/explanation questions are distinguished from present service requests and action-detail replies. Its raw scores and separation margin are saved. Information always permits reads; uncertain action scores permit reads only. Confident action intent permits proposals, never execution. The same bounded support agent resolves references, uses scoped tools, and returns a typed context update. Python checks subjects/choices against current scoped observations and answered subjects against final citations. General policy answers preserve focus and unresolved choices. Invalid or failed outputs preserve context. There is no separate task-continuation classifier or phrase-based subject router.

Action requests additionally use typed new/resume/correct/abandon directives over scoped checkpoints. Information does not advance an action task or charge its counters. Changing conversational focus never retargets a saved proposal. Pending proposals require their specific confirmation/rejection card; natural-language approval does not execute them. Corrections to non-pending tasks clear old target/evidence/cache references. Subjects, tasks and final output save atomically under the conversation reservation and checked versions.

Policy reuse requires exact current ID, revision, locator, text and effective date. Cached passages still require semantic relevance/grounding. Mutable order facts are freshly read; confirmation independently rechecks ownership, current state/version and policy. Per-run limits apply before calls. Once an action task is selected, cumulative limits also apply: 12 executions, 60,000 reported tokens and 24 tool requests. Selecting a task can require an initial bounded agent decision, so a previously exhausted task can incur that resolver call; subsequent task work/proposals are blocked. These are reported-usage gates, not a hard billing ceiling. Deterministic confirmation remains available after model exhaustion.

Migration 012 was applied to the configured demo database on October 1, 2026; its nullable JSONB column was verified. It adds nullable JSON context to existing conversations. `create_all()` does not alter existing tables. No process stays running between messages; in-flight crash recovery is not automatic.

## Jev classification evaluations

`evals/jev_cases.json` contains 24 development and 12 holdout cases, including saved failures and contextual pairs. Labels are authored expectations for review, not measured quality. Evals compare intent and application branch separately and flag false action routing and unnecessary clarification. The runner records all raw scores, margin, usage, errors and latency; failures do not retry. It uses the application's input precheck and threshold policy. Reports are local; nothing is uploaded to Logfire.

```sh
# Validate labels only; no provider calls.
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m backend.customer_support.evals.jev

# Paid classifier-only smoke: run only with explicit authorization, 3 sequential calls.
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m backend.customer_support.evals.jev --live --split development --limit 3

# Re-score saved observations without calling providers.
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m backend.customer_support.evals.jev --replay /tmp/support-jev-eval.json --split development --limit 3 --output /tmp/support-jev-replay.json
```

A call batch is capped at ten cases; `--offset` selects later cases within a split. Development and holdout reports must remain separate; holdout cases should not be used to tune prompts. After explicit authorization, a three-case development classifier smoke matched all labels and application branches: the two saved eligibility questions scored information 0.93/0.92, and a polite cancellation request scored action 0.97. It used Jev 1.13.0 and 6,396 input + 204 output tokens. No support-agent run or action execution occurred. The holdout set and broader live accuracy remain unverified. Scripted conversation regressions demonstrate persistence, subject/task separation, ownership and action boundaries; they cannot demonstrate that a live model resolves natural language correctly.

The architecture modal now uses shared `ArchitectureGraph` boxes and labeled edges in the Incident diagram style. It shows the bounded tool/evidence loop, independent subject memory, Jev verification, proposal-specific confirmation and separate human-review branch. Pan/zoom and fit controls are available; runtime behavior is unchanged.
