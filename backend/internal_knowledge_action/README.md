# Internal Knowledge + Action Assistant

**Status:** Runnable cited-answer and approval-gated mock action demo.

## Demo contract

- **Input:** a selected demo persona and question about synthetic documents, tickets, and policy records. The selector simulates identity; it is not authentication.
- **Output:** a cited answer, explicit abstention, or one proposed support follow-up task awaiting a simulated approver. Grounded answers that cite an authorized support ticket offer a follow-up action in chat; the user submits that explicit request, and approval writes only a local synthetic task record.
- **Dominant design decision:** filter sources by the user's access **before** retrieval, and keep evidence-backed answers separate from approval-gated actions.

## Intended flow

```text
Request schema/length checks -> action keyword signals -> Jev intent + app threshold
  answer -> requester ACL -> lexical + semantic search -> Markdown cited answer
  action -> requester ACL -> authorized ticket -> typed proposal -> approval
        -> execution-time policy recheck -> idempotent local mock task
```

The fixture is `fixtures/corpus_v3.json`: ten substantial, multi-paragraph synthetic sources cover time off, expenses, security, onboarding, two support cases, on-call, incident response, release operations, and deployment. A simulated sign-in selects Alex in Support or Morgan in Engineering; the UI offers different suggested questions for each role. This is a demo persona selector, not authentication. Each answer request carries up to six prior question/answer pairs with an 8,000-character total cap. The bounded context helps resolve follow-ups and expands the retrieval query, but it is not evidence: cited claims must still come from passages retrieved under the current persona's ACL. Alex can read common policies and support cases; Morgan can read common policies and engineering documents. Each source yields multiple chunks, so retrieval has to choose relevant passages within a document as well as among documents. Explicit ingestion parses sources into exact-locator chunks, embeds new or changed revisions, updates ACL-only changes without re-embedding, and persists a local Git-ignored index. At query time the backend resolves the selected persona, filters chunks by ACL, embeds the contextualized question, runs BM25-style lexical and exact vector scoring over only authorized chunks, fuses the candidate ranks, and applies a bounded deterministic rerank. A prompt-injection sentence in one engineering document remains source text.

The frontend has a **Build mock fixture index** button. The architecture modal explains the ingestion and retrieval internals; routine chat asks go through retrieval, answer verification, and persistence as one workflow. The mock provider returns deterministic vectors with a few synthetic synonym mappings; it exercises the architecture but does not establish semantic retrieval quality. The production-shaped OpenAI embedding adapter is available for an explicitly selected component run. Neither normal offline tests nor the UI's mock-index button call a paid provider. The local index stands in for a production full-text/vector store; it is not a scalable search service.

The **Answer with citations** path uses the same ACL-scoped retrieval. Each ranked chunk supplies its exact surrounding paragraph when it fits the context cap, so adjacent instructions can reach the model. It freezes up to three exact passages for the run, calls a bounded typed answer model, checks cited IDs and source offsets in application code, then asks Jev whether each claim is supported. The typed answer selects paragraph, bullet-list, or numbered-list formatting; Markdown is rendered without raw HTML, and citations stay attached to each verified claim. Missing evidence, invalid citations, low support, or Jev unavailability produce an abstention.

For action-like requests, the backend validates and normalizes the request, runs deterministic keyword checks, then calls Jev only when signals are present. The application applies the intent threshold. Informational requests continue through read-only retrieval; explicit action requests resolve persona ACLs and retrieve authorized ticket passages before the proposal model runs. The only supported proposal is `support_follow_up`. Deterministic policy checks its type, fields, cited passage IDs, ticket type, and requester scope. The proposal does not create a task. A simulated support lead can approve or reject it; an engineering approver is denied. At approval, policy rechecks the current persona ACL and source revision, then a stable idempotency key creates one local task. Repeated approval returns the same task. The persona and approver selectors are simulated identity, not authentication. No external action system is called.

Endpoints: `GET /agent/internal_knowledge_action/personas`, `GET /agent/internal_knowledge_action/index-status`, `POST /agent/internal_knowledge_action/index-fixture` (mock only), `POST /agent/internal_knowledge_action/answer-stream`, saved answer list/detail routes, `GET /agent/internal_knowledge_action/approvers`, and `POST /agent/internal_knowledge_action/actions/{run_id}/decision`. The index must match the fixture's content, revisions, ACLs, and embedding model before query. To run explicit ingestion from the repo root:

Apply migrations 007 and 008 to existing databases after migration 006. Migration 008 creates the idempotent `knowledge_mock_tasks` table. Live answers/action proposals need `OPENAI_API_KEY` and `TYPESAFE_API_KEY`; routine checks use fakes and call neither provider.

```sh
.venv/bin/python -m backend.internal_knowledge_action.ingest_fixture --provider mock
# Live embedding calls only when separately authorized:
# .venv/bin/python -m backend.internal_knowledge_action.ingest_fixture --provider openai
```

`fixtures/retrieval_eval_v3.json` contains 27 labeled lookups across the new topics, paraphrase and passage-specific queries, ACL-denied requests, and no-answer questions. The mock evaluation reports recall@3 1.0, precision among returned sources 0.667, top-1 accuracy 0.857, no-answer accuracy 1.0, and zero unauthorized candidates/results. Precision is intentionally visible: several queries return multiple authorized passages, including some that are not labeled relevant. These mock-vector metrics validate wiring only; they do not establish semantic retrieval quality.

Phase 3 adds one approval-gated mock task and Markdown-formatted answer output. See `AGENTS.md` for phase boundaries, approved plan, and implementation review status.

## Boundaries and acceptance

No live company data or external action writes. Retrieved text is data, not instructions. ACL filtering prevents unauthorized documents from entering ranking, model context, saved payload, or output. Citation checks establish provenance; Jev judges semantic support and intent, both of which remain fallible. Mock embeddings do not establish semantic retrieval quality, and mocked model checks do not establish live answer or proposal quality. Simulated approval is not real authentication or organizational authorization.

Run offline checks from the repository root:

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/internal_knowledge_action/tests -v
```
