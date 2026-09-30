# Research & Workflow agent guide

## Status

This is a runnable portfolio demo. Phase 1 of the incident follow-up was approved, implemented, and reviewed by the user on 2026-09-30. The shared `llm_runs` migration and in-app ordered execution walkthrough remain future phases requiring their own concrete plans and approval.

## Contracts and boundaries

- Keep request, tool, provider, evidence, and output Pydantic contracts in `backend/research_workflow/contracts.py`. Agent and integration modules import those contracts; they do not define their own request or result models.
- Tavily Search supplies discovery results only. The model can inspect result IDs returned during its run; it cannot pass arbitrary URLs to extraction. Only inspected, stored exact passages become citable evidence.
- Apply the company and `as_of` scope in Python. Tavily publication timestamps are estimates and extracted pages are retrieved at run time, so historical availability is not proven by the provider response.
- Do not cite mutable Yahoo snapshot metrics as historical evidence. Exclude daily close prices on the cutoff date. The current financial statement tool declines requests whose `as_of` is more than ten minutes old.
- Preserve saved research-specific payloads and checkpoint behavior. The Phase 1 provider switch changes the request fingerprint through the tool version; existing saved runs remain readable.

## Phase 1 review gate

Offline verification covers contract validation, Tavily response filtering and partial failures, company scoping, selected-result extraction, evidence scope, and a fake-model multi-tool agent run. These checks do not establish live Tavily behavior, live briefing quality, or historical page availability. Do not use `research_smoke.py` as a routine check.
