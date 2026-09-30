# Internal Knowledge + Action Assistant

**Status:** Phase 1 ingestion and hybrid retrieval preview. The cited-answer assistant and action executor are not implemented. The frontend still labels this system an architecture scaffold.

## Demo contract

- **Phase 1 input:** a selected demo persona and question about synthetic documents, tickets, and policy records. The selector simulates identity; it is not authentication.
- **Phase 1 output:** ingestion counts, index status, authorized lexical and vector candidates, reranked excerpts with exact character offsets and revisions, and an ordered explanation of checks. It does not generate an answer or perform an action. Contracts are in `contracts.py`.
- **Later output:** a cited answer and an approval-gated mock action proposal, as planned in `AGENTS.md`.
- **Dominant design decision:** filter sources by the user's access **before** retrieval and separate read-only answer tools from action tools governed by policy and approval.

## Intended flow

```text
User identity -> ACL filter -> lexical + semantic search -> cited answer
             -> optional action proposal -> policy check -> approval -> execute
```

Phase 1 uses `fixtures/corpus_v2.json`: four multi-paragraph synthetic sources cover a leave policy, a refund case, an on-call guide, and a deployment note. Alex in Support can read the common policy and support ticket; Morgan in Engineering can read the common policy and engineering documents. Each source yields multiple chunks, so retrieval has to choose relevant passages within a document as well as among documents. Explicit ingestion parses sources into exact-locator chunks, embeds new or changed revisions, updates ACL-only changes without re-embedding, and persists a local Git-ignored index. At query time the backend resolves the selected persona, filters chunks by ACL, embeds the question, runs BM25-style lexical and exact vector scoring over only authorized chunks, fuses the candidate ranks, and applies a bounded deterministic rerank. A prompt-injection sentence in one engineering document remains source text.

The frontend has a **Build mock fixture index** button and then a read-only retrieval preview. The mock provider returns deterministic vectors with a few synthetic synonym mappings; it exercises the architecture but does not establish semantic retrieval quality. The production-shaped OpenAI embedding adapter is available for an explicitly selected component run. Neither normal offline tests nor the UI's mock-index button call a paid provider. The local index stands in for a production full-text/vector store; it is not a scalable search service. No answer model or action is used in Phase 1.

Endpoints: `GET /agent/internal_knowledge_action/personas`, `GET /agent/internal_knowledge_action/index-status`, `POST /agent/internal_knowledge_action/index-fixture` (mock only), and `POST /agent/internal_knowledge_action/retrieval-preview`. The index must match the fixture's content, revisions, ACLs, and embedding model before query. To run explicit ingestion from the repo root:

```sh
.venv/bin/python -m backend.internal_knowledge_action.ingest_fixture --provider mock
# Live embedding calls only when separately authorized:
# .venv/bin/python -m backend.internal_knowledge_action.ingest_fixture --provider openai
```

`fixtures/retrieval_eval_v2.json` contains twelve labeled allowed, paraphrase, passage-specific, and no-answer cases. Offline metrics report recall@3, precision among returned sources, top-1 accuracy, no-answer accuracy, and unauthorized-source count across both candidate paths and final results; mock metrics validate wiring only. The initial mock run yields 1.0 recall@3, 0.944 precision, 1.0 top-1 and no-answer accuracy, and zero unauthorized sources. One unrelated but authorized policy chunk enters the top three for a refund question, illustrating why passage relevance still needs evaluation.

The next phases add an answer model, citation verification, saved workflow, and one approval-gated mock task. See `AGENTS.md` for phase boundaries.

## Boundaries and acceptance

No live company data or external writes. Retrieved text is data, not instructions. Phase 1 verifies that unauthorized documents never enter ranking or the preview output. It does not yet verify model context, citation quality, action approval, or persistence.

Run Phase 1 offline checks from the repository root:

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/internal_knowledge_action/tests -v
```
