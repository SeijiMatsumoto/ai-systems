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
| 4. Frontend | Incident workspace with timeline, evidence, tool steps, and review state | Reviewed and committed |
| 5. Scenario checks and docs | Offline cases and accurate portfolio documentation | Reviewed and committed (`88dc4ec`); final review brief committed (`b3c9a17`) |

## Log-stream entry-point rework

The rework is complete as an interview portfolio demo. Changes were reviewed
before their commits to `main`.

| Phase | Outcome | Status |
| --- | --- | --- |
| 1. Stream and group | Versioned replay fixture, signature groups, cross-service correlation, deterministic candidate rules | Reviewed and committed |
| 2. Classify and trigger | Jev judgment, application gate, detected incident, snapshot-scoped investigator | Reviewed and committed |
| 3. UI and scenario checks | Replay controls, saved harness trace, labeled scenarios, component smoke tests, and engineer review | Reviewed and committed (`88dc4ec`, `b3c9a17`) |

Phase 1 adds `fixtures/v2/`, `detection.py`, and `replay_cli.py`. The new
fixture derives from v1 and adds a short email retry burst plus an inventory
cache fallback that meets candidate rules but is labeled nonincident. The
deterministic replay emits one JSON step per log and two candidate groups.
Its labels are kept in `expected_detection.json`, outside replayed telemetry.
Phase 2 adds a TypeSafe Jev adapter with a Logfire span for each call, provisional
probability gates, one top-level simulation run, backend response and SSE routes,
and trigger-time snapshots for the existing investigator. Simulations default to
one report and accept a bounded `max_reports` value of 1–3; a process-local gate
serializes investigator runs across both simulation and old alert routes. The UI
exposes the report cap with a control defaulting to 1; it changes reports per
replay, while the backend still runs one investigator at a time. Offline tests
use fake Jev and Pydantic AI responses. The frontend uses the replay route and
exposes the key workflow decisions.

## Current implementation

As of 2026-09-29, `fixtures/v2/` and `detection.py` replay all logs but group only errors;
`classifier.py` judges candidates with Jev; and `simulation.py` invokes a
trigger-time, snapshot-scoped investigator. `api.py` exposes final and SSE
simulation routes. `frontend/src/IncidentWorkspace.tsx` starts a paced replay,
controls the report cap, and splits execution from output into Run and Result
tabs. Run shows five expandable stages: group membership, candidate gate decisions,
Jev inputs and judgments, the agent tool loop, and verification and persistence.
The user removed the separate log, classifier,
complete execution record, and duplicate tool-step panels; the full workflow
payload remains saved in the database. Result opens on completion and shows reports,
citations, coverage gaps, and engineer-review state. Selected simulations use
`/incident-investigation/:runId?tab=run|result` so a reload or shared URL
restores the result and selected tab.
Result now includes a saved engineer approval stage for each verified report.
Reviewers can approve or request changes with a note; decisions are stored in
the existing simulation payload and are immutable for that report. The demo
has no reviewer identity or authorization and does not trigger remediation.
The result view leads with a compact decision brief derived from the saved
report, placing the trigger before the cause hypothesis and the primary unknown.
The full report and source ledger are available in one expandable section.
`smoketests/` contains separate CLI scripts for the two Jev candidate calls and
for the investigator's first query and final draft model requests. Each script
uses pinned input and checks one model response; neither investigator script runs
the full agent loop or writes to Neon. The earlier combined `smoke.py` was removed.
On 2026-09-29, all four named scripts were run against their real providers:
checkout classified as incident, inventory landed in the safe `needs_review`
band, the first investigator response chose one scoped `search_logs` call, and
the draft response passed citation verification. The scripts are paid checks and
remain outside routine test discovery. Keep the inventory calibration result
visible instead of calling it `not_incident`.
The Run view displays only ERROR replay records that entered grouping and candidate
evaluation; backend replay and saved workflow still retain the full fixture.
The frontend allocates a UUID on click, selects it in the saved-run control, and
passes it to the simulation stream; the backend uses that UUID for `llm_runs` and
the saved output. A prominent current-task line follows the latest streamed stage.
The collapsible React Flow diagram shows component boundaries.
Simulation reports and workflow steps are saved in `incident_simulation_outputs`
and can be reopened from the frontend. Migration 005 was applied to this
checkout's configured Neon database on 2026-09-29. The older v1 alert API is
still runnable but is no longer the frontend entry point. The incident demo is
complete for portfolio use. Its classifier thresholds have limited live
calibration, report approval has no reviewer identity or authorization, and the
report's cause remains a hypothesis until an engineer verifies it. Do not
describe these demo boundaries as production guarantees.

Follow-up after incident work: connect `backend/research_workflow/` to `llm_runs` so its existing research runs can be found in the shared registry. Preserve research-specific payloads and behavior during that migration.
