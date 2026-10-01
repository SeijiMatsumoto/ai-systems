# Customer Support Agent

**Status:** Phase 1 foundation implemented; awaiting review. Typed records, a synthetic camera-store fixture, and read-only store methods run locally. Conversation API, retrieval/model orchestration, action execution, case persistence, and chat UI are planned.

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

The store uses immutable local fixtures, without a database or embedding index. It demonstrates scoped authoritative reads. Policy hybrid retrieval/reranking will be added in Phase 2; current exact policy lookup is not semantic retrieval. Simulated sign-in resolves one of the fixture customers; it is not authentication for real users.

## Run offline checks

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/customer_support/tests -v
```

No provider calls or external writes occur in these tests. Detailed phase scope and review gates are in `AGENTS.md`.
