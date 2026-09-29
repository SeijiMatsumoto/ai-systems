# Incident Investigation & Reporting Agent

**Status:** synthetic telemetry fixture, read-only query layer, bounded investigator, citation checks, and backend API are implemented. The frontend execution path is pending.

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

`telemetry.py` loads and validates the fixture, derives an investigation scope from the alert, and exposes four read-only queries: `search_logs`, `get_metric_series`, `inspect_trace`, and `list_changes`. They enforce service and time bounds, validate filters, cap results, and return source locators plus truncation or coverage-gap metadata. They are Python functions wrapped as agent tools, not HTTP routes yet.

`agent.py` exposes those queries as typed tools for one Pydantic AI investigator. The model sees the alert, allowed services, available metric names, and declared coverage gaps, then chooses follow-up queries. Metric results are condensed to at most 12 exact points with evidence IDs. Python records each tool step and enforces an eight-call application budget plus model request/token/time limits. `verification.py` resolves cited IDs to source records, rejects IDs that were not surfaced or are outside scope, checks claim placement, orders the timeline, and discloses fixture coverage gaps. It does not establish that free-form claim text accurately interprets a source; engineer review is always required. A draft with no cited observations or failed checks fails the run.

`POST /agent/incident_investigation` on `backend.main:app` accepts an alert, service, and time window. It returns the cited report or structured verification issues, run status, stop reason, tool steps, usage, and optional Logfire trace ID. The report and tool steps are response-only; `llm_runs` persists the run identity and state, not the report. There is no incident frontend yet.

The incident telemetry is the checked-in synthetic fixture, not data fetched from Logfire. The agent's tool steps are returned in memory. With a telemetry-write `LOGFIRE_API_KEY` (or `LOGFIRE_TOKEN`) and `LOGFIRE_SEND_TO_LOGFIRE=true`, the service exports its run span and records its trace ID in `llm_runs`. When export is disabled, that field remains empty. The shared backend setup also instruments Pydantic AI. Offline tests disable export and make no live model calls.

The next phase will add a UI showing the timeline beside the tool trace and source excerpts.

## Offline checks

```sh
.venv/bin/python -m unittest discover -s backend/incident_investigation/tests -v
```

These tests inspect the fixture, query behavior, draft agent, report checks, and API response with a local fake model. They make no real LLM calls, Logfire export, or external telemetry queries.

## Boundaries and acceptance

No automated remediation or production telemetry access. Queries should be scoped by service and time, with bounded results and an explicit stop budget. The demo is sufficient when one known fixture yields a plausible cited report, one misleading correlation remains labeled as a hypothesis, and missing telemetry is disclosed instead of invented.
