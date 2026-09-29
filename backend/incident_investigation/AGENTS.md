# Incident Investigation work guide

Follow the repository-root `AGENTS.md` as well. This file records the incident demo's decisions and phase progress so work can resume without treating a plan as implemented code.

## Approved direction

- Build one interview portfolio demo around a substantial, versioned synthetic incident spanning several services.
- Include correlated logs, metric series, trace spans, alerts, and deployment records, with routine noise, missing data, and a misleading nearby correlation.
- Expose the incident data through scoped, read-only query tools. Keep service, time-window, and result limits in application code.
- Use one bounded investigator to choose follow-up queries and produce a report for engineer review. Resolve evidence IDs and check claims in application code.
- Keep incident evidence separate from Logfire traces of the investigator's own execution. Do not use production telemetry or automate remediation.

## Phase progress

The user approved this overall sequence, not the implementation details of any phase. Present a concrete plan and wait for approval before starting each phase. After implementation, run relevant offline checks and summarize the uncommitted result for user review. Commit to `main` only after the user approves the implementation. Do not plan the next phase before that review.

| Phase | Outcome | Status |
| --- | --- | --- |
| 1. Fixture and query tools | Multi-service synthetic telemetry and bounded read-only queries | Reviewed and committed (`0922f12`) |
| 2A. Shared run registry | Minimal cross-system run ID, state, and Logfire trace ID | Reviewed and committed (`9444464`) |
| 2B. Investigation loop | Bounded agent, tool steps, stop reason, and Logfire export | Reviewed and committed |
| 3. Report and verification | Typed cited report, deterministic evidence checks, API response | Reviewed and committed |
| 4. Frontend | Incident workspace with timeline, evidence, tool steps, and review state | Not planned in detail |
| 5. Scenario checks and docs | Offline cases and accurate portfolio documentation | Not planned in detail |

## Current implementation

As of 2026-09-29, `fixtures/v1/` and `telemetry.py` provide synthetic telemetry and four scoped Python queries. `agent.py` and `service.py` provide a bounded investigator using `backend/db/llm_runs.py`. `verification.py` constructs a cited report or structured failures, and `api.py` exposes it through the backend. Offline fake-model tests cover the agent and report checks. There is no incident frontend execution path. Update this section and the phase table after each approved phase. Do not describe an unimplemented phase as runnable.

Follow-up after incident work: connect `backend/research_workflow/` to `llm_runs` so its existing research runs can be found in the shared registry. Preserve research-specific payloads and behavior during that migration.
