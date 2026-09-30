# Incident Investigation & Reporting Agent

**Status:** runnable local demo with synthetic telemetry, read-only queries, a bounded investigator, citation checks, backend API, and an engineer-review frontend.

**Entry-point rework in progress:** the current UI still starts from the v1 alert. A
new offline v2 log replay and deterministic candidate selector are implemented;
Jev classification, automatic investigation triggering, and replay UI are later phases.

## Demo contract

- **Input:** a service, alert ID, and investigation time window over synthetic logs, metrics, traces, and deployment records.
- **Output:** a cited incident timeline, separated facts/correlations/hypotheses, likely causes, unknowns, and a report for engineer review. The proposed data shape is in `contracts.py`.
- **Dominant design decision:** telemetry query services narrow large data before the model sees it. The model investigates and synthesizes; it is not the telemetry source of truth.

## Intended flow

```text
Alert + time window -> deterministic telemetry queries -> bounded evidence set
                   -> investigation loop -> cited claims -> engineer review
```

The checked-in `fixtures/v1/` dataset covers a checkout error spike across gateway, storefront, checkout, payments, and inventory, plus unrelated email-worker traffic. It contains 443 logs, 1,281 minute-level metric points, 180 trace spans, three change records, and one alert. Payments database connection waits rise after a pool limit changes from 40 to 4; checkout errors follow. A nearby storefront deployment is a competing correlation, and payments trace spans have a declared sampling gap from 14:26 to 14:32 UTC. The fixture is deterministic and can be regenerated with `python backend/incident_investigation/fixtures/generate_v1.py`.

### Offline log replay (rework Phase 1)

`fixtures/v2/` preserves the multi-service telemetry without a prewritten alert
and adds two distinct
nonincident cases: two email delivery errors that stay below the candidate
threshold, and three inventory cache refresh errors where a fallback succeeds.
`fixtures/generate_v2.py` derives it reproducibly from v1. Its
`expected_detection.json` contains labels for offline tests and is never fed to
the replay.

`detection.py` replays all 448 logs in timestamp order. It groups identical
service/level/message signatures within five minutes and links warning/error
groups across related services when they share a request or trace ID. Three
distinct error requests in a rolling five-minute window emit one *candidate*
per correlated cluster; subsequent matching errors are recorded as duplicate
candidate steps. This rule does not decide whether the candidate is an incident.
The checkout/payments cluster and inventory fallback cluster both become
candidates. The email retries do not.

To inspect every replay step without making model or provider calls:

```sh
.venv/bin/python -m backend.incident_investigation.replay_cli > /tmp/incident-replay.jsonl
```

Each JSON line contains the original log and locator, signature group and
count, correlated cluster and services, distinct error-request count, decision,
and reason. Replay pacing, classification, and investigation handoff are not
connected yet.

`telemetry.py` loads and validates the fixture, derives an investigation scope from the alert, and exposes four read-only queries: `search_logs`, `get_metric_series`, `inspect_trace`, and `list_changes`. They enforce service and time bounds, validate filters, cap results, and return source locators plus truncation or coverage-gap metadata. They are Python functions wrapped as agent tools, not HTTP routes yet.

`agent.py` exposes those queries as typed tools for one Pydantic AI investigator. The model sees the alert, allowed services, available metric names, and declared coverage gaps, then chooses follow-up queries. Metric results are condensed to at most 12 exact points with evidence IDs. Python records each tool step and enforces an eight-call application budget plus model request/token/time limits. `verification.py` resolves cited IDs to source records, rejects IDs that were not surfaced or are outside scope, checks claim placement, orders the timeline, and discloses fixture coverage gaps. It does not establish that free-form claim text accurately interprets a source; engineer review is always required. A draft with no cited observations or failed checks fails the run.

`POST /agent/incident_investigation` on `backend.main:app` accepts an alert, service, and time window. It returns the cited report or structured verification issues, run status, stop reason, tool steps, ordered workflow steps, usage, and optional Logfire trace ID. `POST /agent/incident_investigation/stream` emits each workflow step as a server-sent event followed by the same final response. The frontend uses the stream to show scope validation, run state, model context and instructions, tool choices and full fixture query results, draft output, citation verification, and stop state while the run progresses. It also shows the timeline, cited evidence excerpts and locators, coverage gaps, and engineer-review requirement. Model private reasoning and provider internals are not exposed in the UI; Logfire holds the detailed instrumented spans when enabled. The report and workflow trace are response-only; `llm_runs` persists the run identity and state, not the report. Reloading the page does not restore a report.

The incident telemetry is the checked-in synthetic fixture, not data fetched from Logfire. The agent's tool steps are returned in memory. With a telemetry-write `LOGFIRE_API_KEY` (or `LOGFIRE_TOKEN`) and `LOGFIRE_SEND_TO_LOGFIRE=true`, the service exports its run span and records its trace ID in `llm_runs`. When export is disabled, that field remains empty. The shared backend setup also instruments Pydantic AI. Offline tests disable export and make no live model calls.

The next phase covers scenario checks and final portfolio documentation.

## Offline checks

```sh
.venv/bin/python -m unittest discover -s backend/incident_investigation/tests -v
```

These tests inspect the fixture, query behavior, draft agent, report checks, and API response with a local fake model. They make no real LLM calls, Logfire export, or external telemetry queries.

## Boundaries and acceptance

No automated remediation or production telemetry access. Queries should be scoped by service and time, with bounded results and an explicit stop budget. The demo is sufficient when one known fixture yields a plausible cited report, one misleading correlation remains labeled as a hypothesis, and missing telemetry is disclosed instead of invented.
