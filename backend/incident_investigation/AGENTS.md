# Incident Investigation work guide

Follow the repository-root `AGENTS.md` as well. This file records the incident demo's decisions and phase progress so work can resume without treating a plan as implemented code.

## Approved direction

- Build one interview portfolio demo around a substantial, versioned synthetic incident spanning several services.
- Include correlated logs, metric series, trace spans, alerts, and deployment records, with routine noise, missing data, and a misleading nearby correlation.
- Expose the incident data through scoped, read-only query tools. Keep service, time-window, and result limits in application code.
- Use one bounded investigator to choose follow-up queries and produce a report for engineer review. Resolve evidence IDs and check claims in application code.
- Keep incident evidence separate from Logfire traces of the investigator's own execution. Do not use production telemetry or automate remediation.

## Phase progress

The user approved this overall sequence, not the implementation details of any phase. Present a concrete plan and wait for approval before starting each phase. After implementation, run relevant offline checks, commit the phase to `main`, and summarize the result for user review before planning the next phase.

| Phase | Outcome | Status |
| --- | --- | --- |
| 1. Fixture and query tools | Multi-service synthetic telemetry and bounded read-only queries | Awaiting detailed plan and approval |
| 2. Investigation loop | Bounded agent, tool steps, and stop reason | Not planned in detail |
| 3. Report and verification | Typed cited report, deterministic evidence checks, API response | Not planned in detail |
| 4. Frontend | Incident workspace with timeline, evidence, tool steps, and review state | Not planned in detail |
| 5. Scenario checks and docs | Offline cases and accurate portfolio documentation | Not planned in detail |

## Current implementation

As of 2026-09-29, `README.md` and `contracts.py` are design scaffolds. There is no incident API, fixture, query tool, agent, or frontend execution path. Update this section and the phase table after each approved phase. Do not describe an unimplemented phase as runnable.
