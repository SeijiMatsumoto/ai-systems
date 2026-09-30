# Research & Workflow agent guide

## Status

This is a runnable portfolio demo. Phases 1 and 2 were reviewed and committed. Phase 2 connects research attempts to `llm_runs`, saves ordered backend steps, and exposes a research SSE route. Migration 006 has not been applied to the configured database. The in-app walkthrough is the next phase and has not been implemented.

## Contracts and boundaries

- Keep request, tool, provider, evidence, and output Pydantic contracts in `backend/research_workflow/contracts.py`. Agent and integration modules import those contracts; they do not define their own request or result models.
- Tavily Search supplies discovery results only. The model can inspect result IDs returned during its run; it cannot pass arbitrary URLs to extraction. Only inspected, stored exact passages become citable evidence.
- Apply the company and `as_of` scope in Python. Tavily publication timestamps are estimates and extracted pages are retrieved at run time, so historical availability is not proven by the provider response.
- Do not cite mutable Yahoo snapshot metrics as historical evidence. Exclude daily close prices on the cutoff date. The current financial statement tool declines requests whose `as_of` is more than ten minutes old.
- Preserve saved research-specific payloads and checkpoint behavior. The Phase 1 provider switch changes the request fingerprint through the tool version; existing saved runs remain readable.
- Each new research attempt has the same UUID in `llm_runs` and `research_runs`. A failed checkpoint remains terminal; a resumed attempt gets a new UUID and `resumed_from_run_id`. Migration 006 backfills existing research rows before enforcing the foreign key. Apply it explicitly to existing databases only after this phase is reviewed.
- `ResearchWorkflowStep` in `contracts.py` is the public step contract. Save each step in `research_run_steps` before sending it over SSE. Step details can contain tool arguments, results, and model-visible context; do not place private model reasoning in them.

## Phase 1 review gate

Offline verification covers contract validation, Tavily response filtering and partial failures, company scoping, selected-result extraction, evidence scope, and a fake-model multi-tool agent run. These checks do not establish live Tavily behavior, live briefing quality, or historical page availability. Do not use `research_smoke.py` as a routine check.

## Phase 2 review gate

Offline verification also covers shared/domain lifecycle linkage, a saved failed checkpoint, a new linked resume attempt, usage payloads, ordered steps, and SSE event order. Migration 006 was checked on a disposable local PostgreSQL database, including backfill and repeat application. These checks do not establish deployed behavior or the frontend walkthrough.
