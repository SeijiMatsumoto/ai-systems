# Internal Knowledge + Action work guide

Follow the repository-root `AGENTS.md`. Phase 1 was reviewed and committed as `21d5907`. Phase 2 was reviewed and committed as `c6196ce`. Phase 3 was approved in conversation on 2026-09-30 and is implemented.

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
| 1. Hybrid retrieval boundary | Versioned corpus, two demo personas, ingestion/upserts, embedded chunks, ACL-scoped lexical and vector retrieval, reranking, exact locators, retrieval eval | Reviewed and committed (`21d5907`) |
| 2. Read-only cited answers | Bounded answer call, citation verification, saved run and steps, frontend walkthrough and answer | Reviewed and committed (`c6196ce`) |
| 3. Approval-gated mock action + Markdown answers | Jev intent classification after deterministic signals, typed task proposal, deterministic policy, explicit approval, idempotent mock execution, safe Markdown answer formatting, UI and scenario checks | Implemented; awaiting review |

## Phase 1 plan for review

**Goal:** demonstrate a production-shaped ingestion and hybrid retrieval flow while ensuring neither candidate search can see a source outside the selected synthetic persona's ACL.

**Technical changes**

1. Keep typed persona, source, ACL, chunk, index, candidate, and exact-locator contracts in `contracts.py`, separate from their consumers.
2. Ingest the versioned synthetic fixture into bounded chunks, embed new/changed source revisions, update ACL-only changes without re-embedding, remove deleted sources, and persist a local index. The UI persona choice remains simulated identity; the backend resolves groups and never accepts ACLs from the request or model.
3. Provide an embedding interface with a real OpenAI adapter and a clearly labeled deterministic mock for offline tests. Query embedding, lexical candidate scoring, vector scoring, rank fusion, and deterministic reranking operate only on ACL-authorized chunks. Keep provider/model identity and source freshness checks with the index.
4. Expose explicit fixture ingestion and index status. Retrieval runs as part of the answer/action workflows; candidate paths and exact locators are directly tested. Keep the assistant labeled incomplete until Phase 2.
5. Add labeled retrieval cases and report recall@3, precision among returned sources, top-1 accuracy, no-answer accuracy, and unauthorized-source count. Mock metrics validate wiring only; real-model quality remains unverified.

**Verification:** offline tests prove fixture validation, exact chunk offsets, idempotent ingestion, changed-document/ACL-only/deletion handling, provider request/response shape, both candidate paths constrained by ACL, paraphrase recall through the vector path, no-answer handling, injection as data, local index persistence, and API failures. Run Ruff, frontend build/lint/tests, and `git diff --check`. No routine live LLM or embedding calls, and no external writes.

**Phase 1 review artifact:** the synthetic corpus and ACL matrix, exact retrieval contract, a worked allowed/denied query trace, test results, and a reviewable diff. Phase 1 was reviewed before this Phase 2 plan was written.

### Phase 1 implementation review

The fixture is `fixtures/corpus_v3.json` (`knowledge-corpus-v3`), with ten multi-paragraph synthetic sources spanning common employee policies, support cases, and engineering procedures. Each source produces multiple chunks. The simulated sign-in selects a demo persona; the request cannot supply groups or source IDs. Explicit ingestion creates versioned chunks and a local `knowledge_index.local` file (Git ignored). The mock embedding provider is a deterministic test double; the real OpenAI adapter is not exercised by routine tests. The local exact vector scan and Python BM25-style scoring stand in for a production database/search index. Search results are bounded to eight candidates per path and three reranked excerpts. Answer requests accept at most six bounded prior question/answer turns; deterministic expansion supports follow-up retrieval, while prior answers never count as current evidence.

| Source | Alex · Support | Morgan · Engineering |
| --- | --- | --- |
| Time off policy | Allowed | Allowed |
| Customer refund queue | Allowed | Denied |
| Engineering on-call rotation | Denied | Allowed |
| Build pipeline note with injection text | Denied | Allowed |

For “What happens to a customer refund request?”, Alex can retrieve the support ticket while Morgan cannot retrieve support-only records. The ten documents produce 151 chunks. The 27-case mock-only evaluation has recall@3 1.0, precision among returned sources 0.667, top-1 accuracy 0.857, no-answer accuracy 1.0, and zero unauthorized candidates/results. Several cases include extra authorized passages in the top three. These numbers do not predict real embedding quality. The preview stops without an answer or action.

## Phase 2 plan for approval: read-only cited answers

**Goal:** answer one knowledge question from an authorized, frozen set of retrieved passages; make the evidence and every accept/abstain decision inspectable in a saved run. No task proposal or execution is part of this phase.

**Technical changes**

1. Add answer-request, run-step, selected-evidence, typed claim/draft, grounding-decision, verification, and saved-answer contracts to `contracts.py`. Give each model-visible passage a run-scoped evidence ID and preserve its title, source ID, revision, exact offsets, and text. The model may cite IDs; only application code constructs final locators and excerpts.
2. Add a read-only answer service that performs deterministic request checks before any model call, loads one fixture/index snapshot, resolves the selected demo persona to server-owned groups, and runs the existing ACL-first hybrid retrieval. Freeze the authorized source IDs and selected evidence catalog for the run. If the request is invalid or no passage clears retrieval gating, abstain without calling the answer model. Record candidate lists, bounded context, and stop reason in ordered steps.
3. Add a bounded typed answer adapter using the repo's Pydantic AI pattern: one answer call, at most three selected passages, explicit untrusted-document framing, and a short cited claim list or abstention. Expose model settings, request limits, provider-reported usage, and the exact model-visible evidence IDs/text in the walkthrough; never claim to expose private reasoning. Fake model adapters cover routine checks. No autonomous retrieval loop is needed for this fixed RAG slice.
4. Verify draft citations deterministically before any semantic judgment: every referenced ID must be in the frozen selected catalog, ACL-authorized, same revision/offset/text as the captured source, and attached to a nonempty claim. Reject unknown, unsurfaced, stale, or unauthorized references. Then use one bounded Jev grounding decision per proposed claim to assess whether the cited text supports its meaning. Jev sees only prechecked evidence; a rejected or unavailable decision produces an explicit abstention, not an unverified answer or a silent repair. Persist verification reasons separately from the answer.
5. Add a knowledge-answer output table keyed by the shared `llm_runs` ID, with a migration after `006`. Save the request, frozen evidence snapshot, ordered steps, draft/verification summary, accepted answer or abstention, usage, and stop reason. A failed provider call must leave a failed run with an inspectable error step. Add a streaming answer endpoint plus saved-run list/detail endpoints, following the incident run-history pattern. The Phase 1 retrieval-preview endpoint was removed after the answer/action workflows made it redundant; current retrieval internals are shown in the system architecture modal.
6. Extend the Knowledge UI with a question-to-answer flow, live ordered steps, exact cited passages, verification state, abstention explanation, and saved-run selection/URL. Keep the existing retrieval candidate inspection accessible. Update the system/root READMEs, frontend status, and architecture diagram to mark only read-only answers as implemented; the approval/action lane stays planned.

**Verification criteria**

- Offline fixture tests cover an allowed policy answer, an allowed restricted-ticket answer, the same ticket denied to Engineering, no relevant passage, an unrelated authorized distractor, fabricated/unsurfaced/stale citation IDs, and the injected build-note sentence treated as data. Each accepted claim has a citable exact passage; a grounding rejection abstains. No restricted passage appears in candidate lists, model context, steps, saved payload, or UI.
- A fake answer provider and fake Jev decision exercise typed request/response shape, call budgets, reported usage, failure handling, and a complete multi-step stream. SQLite-backed tests exercise `llm_runs` transitions, saved steps, replay, and failure records. Frontend tests cover live and saved states, cited excerpts, and abstention. Run Ruff fix/format/check, backend tests, frontend build/lint/tests, and `git diff --check`.
- No routine live model or embedding calls. Report mock-only coverage and separately request authorization for any bounded paid component smoke test before a live end-to-end run.

**Review artifact:** a successful saved cited answer, a saved abstention/denial, the ordered step payloads, citation verification results, offline test evidence, and the committed diff (`c6196ce`). Phase 2 review is complete.

### Phase 2 implementation review

The answer service creates a shared `llm_runs` row and saves the final payload in `knowledge_answer_outputs` (migration 007). It loads one fixture/index snapshot, resolves server-owned ACL scope, uses the two authorized retrieval paths, and exposes at most three exact passages to one typed answer call. Citation IDs are checked against the selected catalog, source revision, exact offsets, and authorized source IDs before Jev judges claim support. The application accepts Jev probability at or above 0.8; rejected or unavailable judgments abstain. There is no repair call or action executor. The UI streams steps, displays cited excerpts and stop reasons, and reopens saved runs from the URL. Search internals are documented in the system architecture modal; no standalone retrieval-preview mode is exposed.

Migration 007 was applied to this checkout's configured demo database on 2026-09-30. An action-like synthetic request was run through the live UI and saved without any provider call; reload restored the abstention and walkthrough. A live answer smoke for “How do I request time off?” (`14c7aef4-749f-4e3b-bbff-945b608ae1a5`) produced two cited claims, and both passed Jev support checks (0.91 and 0.94). This verifies one question path only; broad answer quality remains unverified. Offline tests use fake answer and Jev providers, including a complete streamed answer, denied ACL scope, fabricated/stale citations, provider failure persistence, and the injection sentence as data. The synthetic persona selector is still not authentication, and the mock embedding index is not a real semantic-quality evaluation.

A saved live run for “How do I request time off?” (`29fa725c-0f0e-4bb6-8564-f7e1216b8806`) abstained because the top three isolated sentence chunks omitted the portal submission steps. Retrieval now expands each selected chunk to its exact surrounding paragraph when the paragraph is at most 600 characters; citation verification checks the original ranked chunk lies within the cited source span. The old run remains immutable. The subsequent successful live smoke is recorded above; the fix is verified on one question only.

## Phase 3 acceptance target

**Phase 3:** a natural-language action request can create only a proposal for one mock task type. Policy checks action type, arguments, requester scope, and approval state before execution; recheck policy at execution and use an idempotency key so repeated approval does not create duplicate tasks. Show approve/reject and blocked states in the UI and saved steps. Offline cases include permitted execution, unauthorized proposal, denied approval, repeated execution, and stale policy or source state. No external action API is needed for the demo slice.

### Phase 3 approved implementation plan

**Approval:** the user approved Phase 3 and separately requested Markdown output with numbered and bulleted lists.

1. Add deterministic action keyword checks before a bounded Jev action-intent judgment; apply the threshold in application code. If Jev is unavailable, stop safely. Informational questions continue through the existing read-only path.
2. For explicit actions, resolve the synthetic requester and ACL-filter retrieval before a typed proposal model call. Permit only `support_follow_up`; validate arguments, source IDs, ticket type, and requester scope deterministically. Save the proposal under the existing `llm_runs`-keyed answer output without creating a task.
3. Add simulated approvers and approve/reject states. Recheck requester access and source revision on approval, then insert a task into a local table with a stable idempotency key. Do not call any external action API.
4. Add answer format to the typed answer result (`paragraph`, `bullet_list`, `numbered_list`). Render Markdown through a shared React component with raw HTML disabled. Preserve one citation badge group per verified claim.
5. Update the UI, API, architecture diagram, phase guide, and root/system READMEs. Add offline fakes for Jev, proposal generation, approval, persistence, policy denial, stale source, rejection, and repeated execution.

**Verification:** backend tests cover deterministic signals before Jev, Jev threshold branching, ACL-filtered proposal inputs, provider failure, approver denial/rejection, current access and revision rechecks, idempotent replay, saved steps, and the existing read-only answer and citation boundaries. Frontend tests cover Markdown format propagation and proposal/approval presentation. Run Ruff, the knowledge-system unittest suite, frontend build/lint/tests, and `git diff --check`. No live provider calls.

### Phase 3 implementation review

The implementation adds a Jev intent classifier behind deterministic action signals and a 0.8 application threshold. An explicit action can produce only a typed support-follow-up proposal grounded in the requester's ACL-visible ticket passages. A verified read-only answer offers that action only when a cited ticket is authorized for the support persona; the suggested prompt is explicit, and still passes through Jev, deterministic policy, and human approval. The UI exposes simulated support-lead and engineering approvers; approval rechecks current source revision and ACL before creating one `knowledge_mock_tasks` row with a per-run idempotency key. Rejection, denied approver, provider failure, blocked access, and repeated approval are retained in the saved workflow. Markdown answer format is typed and rendered with raw HTML disabled; citations remain adjacent to each verified claim.

Offline verification passed on 2026-09-30: 31 backend tests with fake providers; frontend build, lint, and 20 tests; Ruff check and format checks; and `git diff --check`. No live Jev or OpenAI calls were made. Migration 008 was later applied to the configured Neon database after a transient DNS failure; schema introspection confirmed the task columns, unique constraints, and foreign key to `knowledge_answer_outputs`. No task records were written during migration. The demo continues to use mock embeddings by default, simulated identities, and local task persistence; it is not a production authorization or task integration. This phase remains uncommitted and awaits review.

## Deferred decisions

- A production implementation would replace the local index with a durable store such as Postgres full-text search plus pgvector, preserving ACL predicates within both candidate queries. Approximate vector indexing requires recall checks under restrictive filters; the fixture uses an exact authorized scan.
- If real authentication or approval authority becomes a requirement, replace the simulated persona control with verified identity and a separate authorized approver. Do not infer those guarantees from this fixture demo.
