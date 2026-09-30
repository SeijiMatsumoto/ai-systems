# Incident Investigation & Reporting Agent

**Status:** runnable local demo with synthetic telemetry, read-only queries, a bounded investigator, citation checks, backend API, and an engineer-review frontend.

**Current entry point:** the UI replays v2 logs, groups them, classifies
candidates with Jev, and conditionally runs the investigator. The older v1
alert-first backend routes remain available for comparison.

## Demo contract

- **Input:** the frontend replays the v2 fixture without a client-supplied alert. A slider sets the maximum reports per replay from 1 to 3; it defaults to 1.
- **Output:** a cited incident timeline, separated facts/correlations/hypotheses, likely causes, unknowns, and a report for engineer review. The proposed data shape is in `contracts.py`.
- **Dominant design decision:** telemetry query services narrow large data before the model sees it. The model investigates and synthesizes; it is not the telemetry source of truth.

## Intended flow

```text
Synthetic log stream -> signature groups -> correlated candidates
  -> Jev classification -> trigger-time telemetry snapshot
  -> bounded investigator -> citation checks -> engineer review
```

The checked-in `fixtures/v1/` dataset covers a checkout error spike across gateway, storefront, checkout, payments, and inventory, plus unrelated email-worker traffic. It contains 443 logs, 1,281 minute-level metric points, 180 trace spans, three change records, and one alert. Payments database connection waits rise after a pool limit changes from 40 to 4; checkout errors follow. A nearby storefront deployment is a competing correlation, and payments trace spans have a declared sampling gap from 14:26 to 14:32 UTC. The fixture is deterministic and can be regenerated with `python backend/incident_investigation/fixtures/generate_v1.py`.

### Offline log replay (rework Phase 1)

`fixtures/v2/` preserves the multi-service telemetry without a prewritten alert
and adds two distinct nonincident cases: two email delivery errors that stay below the candidate
threshold, and three inventory cache refresh errors where a fallback succeeds.
`fixtures/generate_v2.py` derives it reproducibly from v1. Its
`expected_detection.json` contains labels for offline tests and is never fed to
the replay.

`detection.py` replays all 448 logs in timestamp order. Only `ERROR` logs form
groups: matching service and normalized message within five minutes. `INFO`
and `WARN` logs remain in the replay as ungrouped context. Error groups link
across related services when they share a request or trace ID. Three
distinct error requests in a rolling five-minute window emit one *candidate*
per correlated cluster; subsequent matching errors are recorded as duplicate
candidate steps. This rule does not decide whether the candidate is an incident.
The checkout/gateway error cluster and inventory fallback cluster both become
candidates. The email retries do not.

To inspect every replay step without making model or provider calls:

```sh
.venv/bin/python -m backend.incident_investigation.replay_cli > /tmp/incident-replay.jsonl
```

Each JSON line contains the original log and locator, signature group and
count when the log is an error, correlated cluster and services, distinct
error-request count, decision, and reason. This CLI does not call Jev or the
investigator.

### Backend simulation (rework Phase 2)

`POST /agent/incident_investigation/simulate` replays the v2 logs, then sends
only deterministic candidates to TypeSafe Jev. Its `Noul` judgment asks whether
the bounded log and metric summary shows an active user-impacting incident.
Application code routes a probability at or above 0.75 to investigation, at or
below 0.35 to nonincident, and the middle to review. These are provisional demo
thresholds; two live probes are insufficient calibration. A provider error is
reported as `classifier_unavailable` and starts no investigator.

Accepted incidents get an application-created ID and a 20-minute lookback
ending at the trigger log. The investigator sees a snapshot containing only
logs, metrics, and changes observed by that instant, plus traces that had
already ended. By default, at most one accepted candidate launches an
investigator per simulation. Send `{"max_reports": 2}` or `{"max_reports": 3}`
to raise that cap; additional accepted candidates are held for review. The
backend queues investigators so only one runs at a time per server process,
including requests to the older alert route. The process-local queue does not
coordinate multiple server workers. The investigator keeps the eight-tool-call budget and citation
checks. The simulation owns one `llm_runs` row whether or not it finds an
incident. Its Logfire trace contains a dedicated span for each Jev call with
the candidate state, question version, model, probability, usage, and failure
type. Synthetic incident logs remain separate from Logfire execution traces.

`POST /agent/incident_investigation/simulate/stream` accepts an optional client-generated
`run_id`, creates the shared run under that ID, and emits each replay,
guardrail, classifier, investigator, and registry step as an SSE `step` event,
followed by a `result` event. Both routes accept an optional `max_reports` body
(1–3, default 1) and a bounded `replay_delay_ms` (0–50, default 0) and use the
checked-in fixture. The frontend requests 25 ms between logs so a viewer can
watch the stream, signature grouping, correlation clusters, candidate gate,
and later model stages. The UI puts the ID in the path and selected-run control
when simulation starts, and shows the current task above the stages. The Run tab shows only the 55 error logs considered
for grouping and candidacy. It has five expandable stages: log group
membership, considered clusters and gate outcomes, Jev inputs and judgments,
model tool choices and responses, and verification and saved outcome. The complete
workflow payload is saved without a separate full-trace panel. The Result tab holds the final outcome and cited report,
and opens automatically when the run ends. Verified reports open with a single
decision brief: the trigger and observed impact, proposed cause, strongest
supporting observations, and a key unresolved question. The full timeline,
follow-up checks, and exact source records sit behind one disclosure. The
approval prompt states that the engineer accepts the accuracy of the cited draft
and uncertainty, not a confirmed root cause. Reviewers can approve the draft
or request changes with a note. The decision
is saved in the simulation payload and survives reload; the action does not
change telemetry or trigger remediation. A collapsible React Flow architecture diagram shows the
major components, deterministic and model boundaries, and the investigator's
query ↔ evidence loop with scoped telemetry tools. The expanded agent stage
shows each actual tool choice and response.
The response contains `detected_incidents` and `investigations` arrays. The
backend saves the full simulation result to `incident_simulation_outputs`, keyed
by `llm_runs.id`, before returning it. `GET /agent/incident_investigation/simulations`
lists saved runs; `GET /agent/incident_investigation/simulations/{run_id}`
reloads one. Selecting a saved simulation changes the path to
`/incident-investigation/:runId?tab=run|result`; that URL restores the result
and selected tab on reload. The
frontend streams this route and shows key decisions, candidate outcomes, tool
results, reports, and stop reasons. Live calls require
`TYPESAFE_API_KEY`; an accepted incident also calls the configured investigator
model. The offline suite substitutes both providers.

`POST /agent/incident_investigation/simulations/{run_id}/reviews/{incident_id}`
records one decision for a verified saved report: `approved` or
`changes_requested` with a required note. Repeat decisions return 409. Review
data lives in the existing simulation JSON payload, so no new table or migration
is needed; older saved runs begin with a pending review. This demo has no
reviewer identity or access control, so approval is a recorded simulation
decision, not an authorization for operational action.

`telemetry.py` loads and validates the fixture, derives an investigation scope from the alert, and exposes four read-only queries: `search_logs`, `get_metric_series`, `inspect_trace`, and `list_changes`. They enforce service and time bounds, validate filters, cap results, and return source locators plus truncation or coverage-gap metadata. They are Python functions wrapped as agent tools, not HTTP routes yet.

`agent.py` exposes those queries as typed tools for one Pydantic AI investigator. The model sees the trigger, allowed services, available metric names, and declared coverage gaps, then chooses follow-up queries. Parallel tool calls are disabled so each query can use the preceding result and a large model-generated batch cannot exceed the tool budget at once. Metric results are condensed to at most 12 exact points with evidence IDs. Python records each tool step and enforces an eight-call application budget, 10 model requests, 50,000 cumulative tokens, 4,000 output tokens, and a 90-second timeout. The cumulative token count includes cached input tokens. Budget failures record the specific limit and accumulated usage in the workflow. `verification.py` resolves cited IDs to source records, rejects IDs that were not surfaced or are outside scope, checks claim placement, orders the timeline, and discloses fixture coverage gaps. It does not establish that free-form claim text accurately interprets a source; engineer review is always required. A draft with no cited observations or failed checks fails the run.

`POST /agent/incident_investigation` on `backend.main:app` retains the older alert-first API. It accepts an alert, service, and time window and returns the cited report or structured verification issues, run status, stop reason, tool steps, ordered workflow steps, usage, and optional Logfire trace ID. `POST /agent/incident_investigation/stream` emits each step as a server-sent event. The frontend uses the simulation stream instead. It shows scope validation, run state, model context and instructions, tool choices and fixture query results, draft output, citation verification, stop state, timeline, cited evidence and locators, coverage gaps, and engineer-review requirement. Model private reasoning and provider internals are not exposed in the UI; Logfire holds instrumented spans when enabled. The older alert-first route remains response-only. `llm_runs` holds shared run identity and state; the full simulation response and workflow steps live in `incident_simulation_outputs`. Apply `backend/db/migrations/005_create_incident_simulation_outputs.sql` to other existing databases before running this version of the simulation API.

The incident telemetry is the checked-in synthetic fixture, not data fetched from Logfire. The agent's tool steps are returned in memory. With a telemetry-write `LOGFIRE_API_KEY` (or `LOGFIRE_TOKEN`) and `LOGFIRE_SEND_TO_LOGFIRE=true`, the service exports its run span and records its trace ID in `llm_runs`. When export is disabled, that field remains empty. The shared backend setup also instruments Pydantic AI. Offline tests disable export and make no live model calls.

The replay UI uses the v2 fixture. Offline cases cover the checkout incident,
inventory fallback nonincident, below-threshold email retries, uncertain Jev
scores, provider failure, report limits, and concurrent investigator requests.

## Offline checks

```sh
.venv/bin/python -m unittest discover -s backend/incident_investigation/tests -v
```

These tests inspect each boundary before a paid run:

| Component | Offline check |
| --- | --- |
| Replay and candidate gate | All fixture logs replay in order; only errors group; labeled incident and fallback candidates appear once. |
| Jev adapter | Mock TypeSafe request shape, Logfire span, probability thresholds, and unavailable-provider path. |
| Telemetry tools | Service and time scope, bounded records, source IDs, and trigger-time snapshot. |
| Investigator | Scoped tool results, sequential loop, realistic seven-query usage above the old 25,000-token cap, hard-budget failure, and explicit stop reason. |
| Report and storage | Citation resolution, rejected evidence, saved report or failure, shared run state, and SSE event order. |
| Frontend | TypeScript build, lint, and Node tests for run URLs, tab selection, and current-task labels; browser interaction still requires visual review. |

The full mocked simulation produces a cited report and persists its workflow. These checks make no real model calls, Logfire export, or external telemetry queries; they do not establish live provider behavior.

## Paid, single-request model smoke tests

Each script has a pinned input under `smoketests/fixtures/`, checks its own output,
and exits with a nonzero status on failure. Run a single script from the repository
root when you want to inspect that model call:

| Model call | CLI command | Expected output |
| --- | --- | --- |
| Jev, checkout candidate | `.venv/bin/python -m backend.incident_investigation.smoketests.smoketest_checkout_jev` | `incident` |
| Jev, inventory fallback | `.venv/bin/python -m backend.incident_investigation.smoketests.smoketest_inventory_jev` | `not_incident` or `needs_review`; no investigator |
| Investigator, first query choice | `.venv/bin/python -m backend.incident_investigation.smoketests.smoketest_investigator_query` | Exactly one typed, scoped telemetry tool call |
| Investigator, final draft | `.venv/bin/python -m backend.incident_investigation.smoketests.smoketest_investigator_draft` | Typed draft with observations citing only pinned prior tool results |

The investigator scripts each make exactly **one** model request and stop before
executing a tool or continuing the agent loop. The draft script supplies a fixed
history of three synthetic tool results. These checks create no `llm_runs` rows
and do not run the simulation. They print actual output, usage, and a Logfire
trace ID when available. They are paid calls, excluded from routine test discovery,
and load `TYPESAFE_API_KEY` or `OPENAI_API_KEY` from `backend/.env`. Logfire exports
when configured there. The inventory fallback may land in `needs_review`; the
actual probability remains visible for calibration.

## Boundaries and acceptance

No automated remediation or production telemetry access. Queries should be scoped by service and time, with bounded results and an explicit stop budget. The demo is sufficient when one known fixture yields a plausible cited report, one misleading correlation remains labeled as a hypothesis, and missing telemetry is disclosed instead of invented.
