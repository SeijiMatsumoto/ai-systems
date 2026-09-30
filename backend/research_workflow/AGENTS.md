# Research & Workflow agent guide

## Status

This is a runnable portfolio demo. Phases 1, 2, and 3 were reviewed and committed. Phase 3 adds a Jev request judgment with an application gate and visible fallback, plus a live and saved in-app walkthrough with a system diagram. Migration 006 was applied to the configured database on 2026-09-30; all 15 older research rows have matching `llm_runs` rows.

## Contracts and boundaries

- Keep request, tool, provider, evidence, and output Pydantic contracts in `backend/research_workflow/contracts.py`. Agent and integration modules import those contracts; they do not define their own request or result models.
- Tavily Search supplies discovery results only. The model can inspect result IDs returned during its run; it cannot pass arbitrary URLs to extraction. Only inspected, stored exact passages become citable evidence.
- Apply the company and `as_of` scope in Python. Tavily publication timestamps are estimates and extracted pages are retrieved at run time, so historical availability is not proven by the provider response.
- Do not cite mutable Yahoo snapshot metrics as historical evidence. Exclude daily close prices on the cutoff date. The current financial statement tool declines requests whose `as_of` is more than ten minutes old.
- Preserve saved research-specific payloads and checkpoint behavior. The Phase 1 provider switch changes the request fingerprint through the tool version; existing saved runs remain readable.
- Each new research attempt has the same UUID in `llm_runs` and `research_runs`. A failed checkpoint remains terminal; a resumed attempt gets a new UUID and `resumed_from_run_id`. Migration 006 backfills existing research rows before enforcing the foreign key. It has been applied to this checkout's configured database; other existing databases still need it applied explicitly.
- `ResearchWorkflowStep` in `contracts.py` is the public step contract. Save each step in `research_run_steps` before sending it over SSE. Step details can contain tool arguments, results, and model-visible context; do not place private model reasoning in them.
- `ResearchQueryJevJudgment` and `ResearchQueryGateDecision` also live in `contracts.py`. Jev supplies two typed yes/no probabilities; application thresholds make the accept/reject decision. An uncertain or unavailable Jev result invokes the existing query classifier, and both paths remain visible in the run steps. Do not describe the probability as proof that a request is safe.

## Phase 1 review gate

Offline verification covers contract validation, Tavily response filtering and partial failures, company scoping, selected-result extraction, evidence scope, and a fake-model multi-tool agent run. These checks do not establish live Tavily behavior, live briefing quality, or historical page availability. Do not use `research_smoke.py` as a routine check.

## Phase 2 review gate

Offline verification also covers shared/domain lifecycle linkage, a saved failed checkpoint, a new linked resume attempt, usage payloads, ordered steps, and SSE event order. Migration 006 was checked on a disposable local PostgreSQL database, including backfill and repeat application. These checks do not establish deployed behavior or the frontend walkthrough.

## Phase 3 review gate

Offline research tests cover Jev adapter shape and usage, threshold and fallback branches, early rejection before provider prefetch, and a fake-model workflow. Frontend build, lint, and tests cover stream parsing and run navigation. A local mock API demonstrated streaming steps, completed Briefing navigation, and saved Run restoration in the browser. Ruff checks pass on the changed Python files. No live Jev, Tavily, OpenAI, or full research run was called for this phase. The broader interview outline's durable worker queue, generalized planner, parallel subtasks, and human review action remain future design extensions rather than implemented features.

## First live run follow-up

Run `7f7a19ba-a9df-4b15-9f3a-3e4e8226cb40` searched Tavily and inspected three citable web passages, then cited only four SEC filing passages. The model-authored limitation mentioned inspected reporting even though no web passage supported a retained finding. Keep the model free to prefer primary filings; do not force a web citation for coverage. The Briefing UI now derives searched, inspected, and cited Tavily counts from saved steps and final evidence, so source use is explicit without rewriting the saved report. The local port-5174 CORS fix was included in this follow-up.

## Web coverage follow-up

Each Research UI submission gets a fresh `as_of`; the form no longer offers a historical cutoff override. API clients can still provide one. Extraction can return two distinct exact passages per selected page. Jev reviews at most three uncited passages for relevance and novelty; one qualifying passage can prompt one proposed finding, which must pass the existing evidence checks. Final passage dispositions are persisted in steps and shown with the Briefing. The prompt and tool versions are 10. Offline tests cover exact passage offsets, the Jev adapter, a mocked multi-source run with streamed and saved decisions, and a web-review timeout. No paid full research run was used for this follow-up.

The user selected a shorter investor-style default question. The Run tab now shows a compact scrolling task trail shared with the incident demo: new tasks move prior tasks upward and older labels fade. Visible run-ID labels were removed from the research workspace; the shareable URL and internal identifiers remain. Frontend build, lint, tests, and saved-run browser inspection passed.

Key findings now show compact citation keywords beside the unique source count; hover, focus, or click reveals the exact cited value or passage, locator, and source link. The four generic backend limitations were removed from new briefings; old saved payloads remain intact, but the Briefing view hides those exact boilerplate sentences. The two fiscal-year and filing-date limits in the observed report were agent-authored and remain visible. The web timestamp caveat appears next to Tavily source use only when web evidence is cited. Offline checks and a saved-report browser inspection passed.

Citation chips dismiss on outside pointer or focus and on Escape. This was checked in the saved Briefing browser view; no provider calls were made.

Architecture UI follow-up: the research diagram moved from an inline Run disclosure into the shared page-header modal. All five system pages use the same entry point; the three scaffold diagrams are labeled proposed. Frontend checks and browser inspection passed.

Diagram correction: the research diagram separates Jev's model judgment from the application's request threshold, tool/source limits, provenance checks, grounding judgment, repair/exclusion branch, and persisted run state. It does not depict Jev as the sole guardrail. Browser inspection and frontend checks passed.

UI cutoff follow-up: the Research form no longer exposes an `as_of` control. Each UI submission uses a fresh timestamp with a one-minute clock-skew buffer, even after selecting a saved run. The backend retains explicit `as_of` for API clients, evidence scope, and saved-run provenance. The diagram names both model classifiers and explains why the citation existence/scope precheck precedes semantic grounding. Frontend checks and browser inspection passed; no provider call was made.

Deterministic query precheck: before Jev or its fallback classifier, the backend normalizes and validates the question, rejects invalid input, and records topic and instruction-pattern keyword signals in the workflow. Jev receives these as hints, not as a semantic verdict. The query gate and Jev question versions changed so new requests do not reuse old cached decisions. Offline tests cover signal forwarding, invalid input stopping before Jev, and the normal multi-tool workflow; no live model call was made.

Diagram clarification: the scoped-tools branch returns filtered evidence to the research agent, forming the repeatable tool loop. The separate agent-to-provenance arrow represents the draft after the loop. Each connection has its own arrowhead; browser inspection confirmed the direction.
