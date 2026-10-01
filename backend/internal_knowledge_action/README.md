# Internal Knowledge + Action Assistant

**Status:** Runnable cited-answer and approval-gated mock action demo. Phase 3 implementation is awaiting review.

## Demo contract

- **Phase 1 input:** a selected demo persona and question about synthetic documents, tickets, and policy records. The selector simulates identity; it is not authentication.
- **Phase 1 output:** ingestion counts, index status, authorized lexical and vector candidates, reranked excerpts with exact character offsets and revisions, and an ordered explanation of checks. It does not generate an answer or perform an action. Contracts are in `contracts.py`.
- **Output:** a cited answer, explicit abstention, or one proposed support follow-up task awaiting a simulated approver. Grounded answers that cite an authorized support ticket offer a follow-up action in chat; the user submits that explicit request, and approval writes only a local synthetic task record.
- **Dominant design decision:** filter sources by the user's access **before** retrieval and separate read-only answer tools from action tools governed by policy and approval.

## Intended flow

```text
Request schema/length checks -> action keyword signals -> Jev intent + app threshold
  read-only -> requester ACL -> lexical + semantic search -> Markdown cited answer
  action -> requester ACL -> authorized ticket -> typed proposal -> approval
        -> execution-time policy recheck -> idempotent local mock task
```

Phase 1 uses `fixtures/corpus_v2.json`: four multi-paragraph synthetic sources cover a leave policy, a refund case, an on-call guide, and a deployment note. Alex in Support can read the common policy and support ticket; Morgan in Engineering can read the common policy and engineering documents. Each source yields multiple chunks, so retrieval has to choose relevant passages within a document as well as among documents. Explicit ingestion parses sources into exact-locator chunks, embeds new or changed revisions, updates ACL-only changes without re-embedding, and persists a local Git-ignored index. At query time the backend resolves the selected persona, filters chunks by ACL, embeds the question, runs BM25-style lexical and exact vector scoring over only authorized chunks, fuses the candidate ranks, and applies a bounded deterministic rerank. A prompt-injection sentence in one engineering document remains source text.

The frontend has a **Build mock fixture index** button and then a read-only retrieval preview. The mock provider returns deterministic vectors with a few synthetic synonym mappings; it exercises the architecture but does not establish semantic retrieval quality. The production-shaped OpenAI embedding adapter is available for an explicitly selected component run. Neither normal offline tests nor the UI's mock-index button call a paid provider. The local index stands in for a production full-text/vector store; it is not a scalable search service. No answer model or action is used in Phase 1.

The **Answer with citations** path uses the same ACL-scoped retrieval. Each ranked chunk supplies its exact surrounding paragraph when it fits the context cap, so adjacent instructions can reach the model. It freezes up to three exact passages for the run, calls a bounded typed answer model, checks cited IDs and source offsets in application code, then asks Jev whether each claim is supported. The typed answer selects paragraph, bullet-list, or numbered-list formatting; Markdown is rendered without raw HTML, and citations stay attached to each verified claim. Missing evidence, invalid citations, low support, or Jev unavailability produce an abstention.

For action-like requests, the backend validates and normalizes the request, runs deterministic keyword checks, then calls Jev only when signals are present. The application applies the intent threshold. Informational requests continue through read-only retrieval; explicit action requests resolve persona ACLs and retrieve authorized ticket passages before the proposal model runs. The only supported proposal is `support_follow_up`. Deterministic policy checks its type, fields, cited passage IDs, ticket type, and requester scope. The proposal does not create a task. A simulated support lead can approve or reject it; an engineering approver is denied. At approval, policy rechecks the current persona ACL and source revision, then a stable idempotency key creates one local task. Repeated approval returns the same task. The persona and approver selectors are simulated identity, not authentication. No external action system is called.

Endpoints: `GET /agent/internal_knowledge_action/personas`, `GET /agent/internal_knowledge_action/index-status`, `POST /agent/internal_knowledge_action/index-fixture` (mock only), and `POST /agent/internal_knowledge_action/retrieval-preview`. The index must match the fixture's content, revisions, ACLs, and embedding model before query. To run explicit ingestion from the repo root:

The API includes `POST /agent/internal_knowledge_action/answer-stream`, saved answer list/detail routes, `GET /approvers`, and `POST /actions/{run_id}/decision`. Apply migrations 007 and 008 to existing databases after migration 006. Migration 008 creates the idempotent `knowledge_mock_tasks` table. Live answers/action proposals need `OPENAI_API_KEY` and `TYPESAFE_API_KEY`; routine checks use fakes and call neither provider.

```sh
.venv/bin/python -m backend.internal_knowledge_action.ingest_fixture --provider mock
# Live embedding calls only when separately authorized:
# .venv/bin/python -m backend.internal_knowledge_action.ingest_fixture --provider openai
```

`fixtures/retrieval_eval_v2.json` contains twelve labeled allowed, paraphrase, passage-specific, and no-answer cases. Offline metrics report recall@3, precision among returned sources, top-1 accuracy, no-answer accuracy, and unauthorized-source count across both candidate paths and final results; mock metrics validate wiring only. The initial mock run yields 1.0 recall@3, 0.944 precision, 1.0 top-1 and no-answer accuracy, and zero unauthorized sources. One unrelated but authorized policy chunk enters the top three for a refund question, illustrating why passage relevance still needs evaluation.

Phase 3 adds one approval-gated mock task and Markdown-formatted answer output. See `AGENTS.md` for phase boundaries, approved plan, and implementation review status.

## Boundaries and acceptance

No live company data or external action writes. Retrieved text is data, not instructions. ACL filtering prevents unauthorized documents from entering ranking, model context, saved payload, or output. Citation checks establish provenance; Jev judges semantic support and intent, both of which remain fallible. Mock embeddings do not establish semantic retrieval quality, and mocked model checks do not establish live answer or proposal quality. Simulated approval is not real authentication or organizational authorization.

Run offline checks from the repository root:

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/internal_knowledge_action/tests -v
```
