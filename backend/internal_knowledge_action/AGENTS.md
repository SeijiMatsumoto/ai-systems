# Internal Knowledge + Action work guide

Follow the repository-root `AGENTS.md`. Phase 1 was approved and implemented for review. Phases 2 and 3 remain provisional; approval of this roadmap does not approve their implementation.

## Proposed direction

- Demonstrate the access boundary first: a synthetic demo identity is resolved by application code, and its source ACL filters the corpus **before** ranking or model context construction. The persona selector is simulated identity, not authentication; never claim this demo secures real users.
- Use a small, versioned synthetic corpus of documents, tickets, and policy records. Give two personas different document access and include one record whose text tries to redirect the assistant. Freeze the allowed source IDs for each run.
- Make the ingestion and query paths visible: parse synthetic source revisions into exact-locator chunks, embed existing and changed chunks, preserve ACL metadata, and keep an idempotent local index. At query time embed the question and run lexical and vector retrieval over only authorized chunks, then fuse and rerank candidates. The existing shared vector retrieval has no user ACL filter and must not be used here.
- The explicit offline mock embedding provider exercises contracts and execution order, but its curated vectors do not establish semantic search quality. The OpenAI adapter is available for a separately authorized live component test. Keep the provider model/version with the index and rebuild on model changes.
- Use one bounded answer model call after deterministic request checks and retrieval. It returns a typed answer draft containing evidence IDs. Application code resolves exact excerpts and locators from the run-scoped authorized catalog, rejects unauthorized or fabricated citations, and abstains when support is insufficient. Retrieved text is untrusted data.
- Add action intent judgment only when the action phase needs it: deterministic keyword/pattern signals before Jev, then an application decision. The model may propose a mock task; only application policy, a separately recorded approval, and an idempotent executor may change mock task state.
- Reuse the shared `llm_runs` lifecycle and existing FastAPI/React application. Persist the ordered in-app walkthrough with any saved run. Use fake providers in routine checks and no real organization data or external action writes.

## Phase roadmap

| Phase | Reviewable outcome | Status |
| --- | --- | --- |
| 1. Hybrid retrieval boundary | Versioned corpus, two demo personas, ingestion/upserts, embedded chunks, ACL-scoped lexical and vector retrieval, reranking, exact locators, retrieval eval | Revised implementation; uncommitted and awaiting review |
| 2. Read-only cited answers | Bounded answer call, citation verification, saved run and steps, frontend walkthrough and answer | Provisional; detail reviewed after Phase 1 |
| 3. Approval-gated mock action | Typed proposal, deterministic policy, explicit approval state, idempotent mock execution, UI and scenario checks | Provisional; detail reviewed after Phase 2 |

## Phase 1 plan for review

**Goal:** demonstrate a production-shaped ingestion and hybrid retrieval flow while ensuring neither candidate search can see a source outside the selected synthetic persona's ACL.

**Technical changes**

1. Keep typed persona, source, ACL, chunk, index, candidate, and exact-locator contracts in `contracts.py`, separate from their consumers.
2. Ingest the versioned synthetic fixture into bounded chunks, embed new/changed source revisions, update ACL-only changes without re-embedding, remove deleted sources, and persist a local index. The UI persona choice remains simulated identity; the backend resolves groups and never accepts ACLs from the request or model.
3. Provide an embedding interface with a real OpenAI adapter and a clearly labeled deterministic mock for offline tests. Query embedding, lexical candidate scoring, vector scoring, rank fusion, and deterministic reranking operate only on ACL-authorized chunks. Keep provider/model identity and source freshness checks with the index.
4. Expose explicit fixture ingestion, index status, and read-only retrieval preview APIs. Show ingestion outcome, access scope, both candidate lists, reranking, and exact locators in the scaffold UI. Keep the assistant labeled incomplete until Phase 2.
5. Add labeled retrieval cases and report recall@3, precision among returned sources, top-1 accuracy, no-answer accuracy, and unauthorized-source count. Mock metrics validate wiring only; real-model quality remains unverified.

**Verification:** offline tests prove fixture validation, exact chunk offsets, idempotent ingestion, changed-document/ACL-only/deletion handling, provider request/response shape, both candidate paths constrained by ACL, paraphrase recall through the vector path, no-answer handling, injection as data, local index persistence, and API failures. Run Ruff, frontend build/lint/tests, and `git diff --check`. No routine live LLM or embedding calls, and no external writes.

**Phase 1 review artifact:** the synthetic corpus and ACL matrix, exact retrieval contract, a worked allowed/denied query trace, test results, and an uncommitted diff. Wait for review before planning Phase 2 in implementation detail.

### Phase 1 implementation review

The fixture is `fixtures/corpus_v2.json` (`knowledge-corpus-v2`). Each of its four synthetic sources has multiple paragraphs and chunks. The server resolves the selected persona to groups; the request cannot supply groups or source IDs. Explicit ingestion creates versioned chunks and a local `knowledge_index.local` file (Git ignored). The mock embedding provider is a deterministic test double; the real OpenAI adapter is not exercised by routine tests. The local exact vector scan and Python BM25-style scoring stand in for a production database/search index. Search results are bounded to eight candidates per path and three reranked excerpts.

| Source | Alex · Support | Morgan · Engineering |
| --- | --- | --- |
| Time off policy | Allowed | Allowed |
| Customer refund queue | Allowed | Denied |
| Engineering on-call rotation | Denied | Allowed |
| Build pipeline note with injection text | Denied | Allowed |

For “What happens to a customer refund request?”, Alex's scope is the time off policy and support ticket; the ticket is first in both candidate paths, and one selected exact locator is `ticket-support-214@2026-09-30:440-521`. Morgan's scope is the time off policy and two engineering documents, so the support ticket never enters either search and no excerpt is returned. The longer sources produce 57 chunks total. The twelve-case mock-only evaluation has recall@3 1.0, precision among returned sources 0.944, top-1 accuracy 1.0, no-answer accuracy 1.0, and zero unauthorized candidates/results. An unrelated authorized policy passage appears as a lower-ranked result for one refund case. These numbers do not predict real embedding quality. The preview stops without an answer or action.

## Later phase acceptance targets

**Phase 2:** an allowed question produces an answer whose citations resolve to exact authorized fixture excerpts; a restricted or unsupported question abstains without leaking document text. Show deterministic prechecks, ACL scope, ranked results, model-visible context and typed output, citation checks, persistence, and stop reason in the frontend. Save runs under the shared `llm_runs` ID. Test one complete fake-model workflow and a fabricated-citation or prompt-injection failure before any authorized live component smoke call. Update the system README, root README, and frontend status when this becomes runnable.

**Phase 3:** a natural-language action request can create only a proposal for one mock task type. Policy checks action type, arguments, requester scope, and approval state before execution; recheck policy at execution and use an idempotency key so repeated approval does not create duplicate tasks. Show approve/reject and blocked states in the UI and saved steps. Offline cases include permitted execution, unauthorized proposal, denied approval, repeated execution, and stale policy or source state. No external action API is needed for the portfolio slice.

## Deferred decisions

- A production implementation would replace the local index with a durable store such as Postgres full-text search plus pgvector, preserving ACL predicates within both candidate queries. Approximate vector indexing requires recall checks under restrictive filters; the fixture uses an exact authorized scan.
- If real authentication or approval authority becomes a requirement, replace the simulated persona control with verified identity and a separate authorized approver. Do not infer those guarantees from this fixture demo.
