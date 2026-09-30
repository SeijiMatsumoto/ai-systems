# Internal Knowledge + Action Assistant

**Status:** Phase 2 read-only cited-answer demo with saved runs. Approval-gated actions remain planned.

## Demo contract

- **Phase 1 input:** a selected demo persona and question about synthetic documents, tickets, and policy records. The selector simulates identity; it is not authentication.
- **Phase 1 output:** ingestion counts, index status, authorized lexical and vector candidates, reranked excerpts with exact character offsets and revisions, and an ordered explanation of checks. It does not generate an answer or perform an action. Contracts are in `contracts.py`.
- **Phase 2 output:** a cited answer or explicit abstention, plus a saved ordered walkthrough under the shared `llm_runs` ID. The action proposal remains planned in `AGENTS.md`.
- **Dominant design decision:** filter sources by the user's access **before** retrieval and separate read-only answer tools from action tools governed by policy and approval.

## Intended flow

```text
User identity -> ACL filter -> lexical + semantic search -> cited answer
             -> optional action proposal -> policy check -> approval -> execute
```

Phase 1 uses `fixtures/corpus_v2.json`: four multi-paragraph synthetic sources cover a leave policy, a refund case, an on-call guide, and a deployment note. Alex in Support can read the common policy and support ticket; Morgan in Engineering can read the common policy and engineering documents. Each source yields multiple chunks, so retrieval has to choose relevant passages within a document as well as among documents. Explicit ingestion parses sources into exact-locator chunks, embeds new or changed revisions, updates ACL-only changes without re-embedding, and persists a local Git-ignored index. At query time the backend resolves the selected persona, filters chunks by ACL, embeds the question, runs BM25-style lexical and exact vector scoring over only authorized chunks, fuses the candidate ranks, and applies a bounded deterministic rerank. A prompt-injection sentence in one engineering document remains source text.

The frontend has a **Build mock fixture index** button and then a read-only retrieval preview. The mock provider returns deterministic vectors with a few synthetic synonym mappings; it exercises the architecture but does not establish semantic retrieval quality. The production-shaped OpenAI embedding adapter is available for an explicitly selected component run. Neither normal offline tests nor the UI's mock-index button call a paid provider. The local index stands in for a production full-text/vector store; it is not a scalable search service. No answer model or action is used in Phase 1.

The **Answer with citations** path uses the same ACL-scoped retrieval. Each ranked chunk supplies its exact surrounding paragraph when it fits the context cap, so adjacent instructions can reach the model. It freezes up to three exact passages for the run, calls a bounded typed answer model, checks cited IDs and source offsets in application code, then asks Jev whether each claim is supported. Only claims that pass both checks are shown as an answer. Missing evidence, invalid citations, low support, or Jev unavailability produce an abstention. Action-like requests are stopped by a deterministic read-only precheck. The persona selector remains simulated identity; this does not secure real organization data. The UI shows the ordered steps, model-visible context, judgments, and saved history. Answering calls live model providers; offline tests use fakes.

Endpoints: `GET /agent/internal_knowledge_action/personas`, `GET /agent/internal_knowledge_action/index-status`, `POST /agent/internal_knowledge_action/index-fixture` (mock only), and `POST /agent/internal_knowledge_action/retrieval-preview`. The index must match the fixture's content, revisions, ACLs, and embedding model before query. To run explicit ingestion from the repo root:

Phase 2 adds `POST /agent/internal_knowledge_action/answer-stream`, `GET /agent/internal_knowledge_action/answers`, and `GET /agent/internal_knowledge_action/answers/{run_id}`. Apply `backend/db/migrations/007_create_knowledge_answer_outputs.sql` to an existing database after migration 006. A new database initialized from ORM metadata includes the answer table. Live answers need `OPENAI_API_KEY` and `TYPESAFE_API_KEY`; routine checks do not call either provider.

```sh
.venv/bin/python -m backend.internal_knowledge_action.ingest_fixture --provider mock
# Live embedding calls only when separately authorized:
# .venv/bin/python -m backend.internal_knowledge_action.ingest_fixture --provider openai
```

`fixtures/retrieval_eval_v2.json` contains twelve labeled allowed, paraphrase, passage-specific, and no-answer cases. Offline metrics report recall@3, precision among returned sources, top-1 accuracy, no-answer accuracy, and unauthorized-source count across both candidate paths and final results; mock metrics validate wiring only. The initial mock run yields 1.0 recall@3, 0.944 precision, 1.0 top-1 and no-answer accuracy, and zero unauthorized sources. One unrelated but authorized policy chunk enters the top three for a refund question, illustrating why passage relevance still needs evaluation.

The remaining phase adds one approval-gated mock task. See `AGENTS.md` for phase boundaries.

## Boundaries and acceptance

No live company data or external action writes. Retrieved text is data, not instructions. Phase 2 verifies that unauthorized documents never enter ranking, model context, saved payload, or output. Citation checks establish provenance; Jev judges semantic support, which is still fallible. Neither mocked checks nor the fixture establish live answer quality. Action approval is not implemented.

Run offline checks from the repository root:

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/internal_knowledge_action/tests -v
```
