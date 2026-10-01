# Customer Support Agent

**Status:** Phase 1 committed (`5f82918`); Phase 2 conversation backend implemented and awaiting review. The backend supports owned conversations, policy retrieval, read-only tools, grounded answers, saved runs, and streaming steps. Action execution, case creation, and the chat UI are planned. Live provider quality and the configured PostgreSQL migration remain unverified.

## Architecture

The demo follows the Customer Support architecture in the Notion interview outline: separate policy retrieval, authoritative account/order reads, and checked action tools. Camera equipment makes the examples concrete. The eventual flow is:

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

Conversation state holds recent relevant turns and structured references, and never replaces current order reads. Future escalation handles explicit human requests, ambiguity, unsupported requests, low confidence, and repeated tool failures. Mutations require idempotency and state rechecks. Refunds always become human-review cases; the AI never issues or promises them.

## Phase 1 foundation

- `contracts.py`: strict, immutable domain records and bounded lookup arguments. `SupportRequest` excludes customer identity; extra fields are rejected.
- `fixtures/store_v1.json`: two synthetic customers, seven orders, five Canon camera/lens catalog records, three established camera/lens pairings, and five fictional retailer policies.
- `store.py`: read-only catalog/policy/compatibility methods and customer-bound order methods. Foreign and missing orders produce the same not-found result.
- `tests/test_store.py`: offline component coverage for inputs, fixture integrity, isolation, states, provenance requirements, and failure cases.

The fixture uses a fixed scenario date of October 1, 2026. Prices, addresses, customer names, retailer terms, and transactions are fictional. Canon pairings were checked using Tavily search/extraction of Canon's official announcement; each established pairing stores the URL, locator, and check date. The catalog is deliberately small: absent pairings return `unknown`, even where a broader real-world compatibility rule might apply. Adapter support and individual camera features are outside this lookup. Incompatible-result behavior is exercised with a test fixture; no unsupported incompatibility claim is published in the catalog.

Customer/order/catalog state remains in immutable local fixtures. `PolicyRules` stores return-window days, warranty-review days, permitted fulfillment states, and the refund prohibition. Policy templates render their values from these fields; `review_order` uses the same fields to compute read-only window/state eligibility. These results are not action authorization or return/refund approval.

`retrieval.py` explicitly ingests only policy passages, then combines BM25-style lexical scoring with vector similarity, reciprocal-rank fusion, and a bounded deterministic rerank. It returns at most three passages. Missing or mismatched indexes fail explicitly; the runtime never silently creates mock embeddings. Mock vectors demonstrate this boundary and do not establish semantic retrieval quality.

Simulated sign-in creates an opaque server-owned session token for a fixture customer. This is demo identity selection, not authentication for real users. Order tool arguments and message payloads cannot supply another customer ID. Conversations are scoped to their session token; order lookups are scoped to the session's customer.

## Phase 2 flow and limits

`providers.py` defines the bounded support-model and Jev adapters. `service.py` validates and records keyword signals before Jev classification, applies a probability threshold, and runs a single model loop with read-only tools. Each model call has context/token checks; every tool call has strict argument validation. Current order details are read again for follow-ups. Up to four prior turns are included, with bounded text and owned order/product references; prior assistant answers are never evidence.

The loop permits eight model turns, six tool executions, a 20,000 reported-token budget, a 120-second deadline, and at most one answer repair. Individual provider requests have timeouts; support-model responses are capped at 1,600 output tokens. The token budget checks provider-reported usage and constrains later requests; it is not an exact pre-billing cost guarantee.

Answers contain Markdown paragraphs or lists and grouped exact citations. Deterministic checks reject unknown evidence IDs, unsupported numeric/order references, and obvious execution/refund claims before Jev judges semantic grounding. The application accepts grounding only at probability 0.8 or above. Citation checks establish provenance, not semantic truth; fake-provider tests do not prove live grounding quality. Clarification text receives deterministic checks too.

Actions, explicit human requests, unsupported operations, low confidence, unavailable policy search, and unresolved failures return `clarification` or `handoff_needed`. No human-review case exists yet, and the backend never returns an invented case ID. `repository.py` stores conversations and complete run outputs under shared `llm_runs`, with ordered steps, evidence, provider usage, and stop reasons. One active run per conversation prevents interleaved messages; interruption saves a failed outcome and releases the reservation. Process-crash recovery is not implemented.

## Setup

Apply `backend/db/migrations/009_create_support_conversations.sql` to an existing configured PostgreSQL database after migration 004. New database initialization includes the ORM tables. Migration 009 has not been applied to this checkout's configured database; offline persistence tests use isolated SQLite tables.

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
- `POST /conversations/{id}/messages/stream`: the same payload, with SSE `started`, ordered `step`, and persisted `completed` events; heartbeat comments keep the stream active.

Conversation routes require `Authorization: Bearer <demo token>`. Backend routing is registered in `backend/main.py`; the frontend entry remains planned until Phase 4.

## Run offline checks

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/customer_support/tests -v
```

No provider calls or external writes occur in these tests. Detailed phase scope and review gates are in `AGENTS.md`.
