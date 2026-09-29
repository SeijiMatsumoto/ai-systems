# Incident Investigation & Reporting Agent

**Status:** synthetic telemetry fixture and read-only query layer are implemented. There is no incident API, investigation agent, report verifier, or frontend execution path yet.

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

`telemetry.py` loads and validates the fixture, derives an investigation scope from the alert, and exposes four read-only queries: `search_logs`, `get_metric_series`, `inspect_trace`, and `list_changes`. They enforce service and time bounds, validate filters, cap results, and return source locators plus truncation or coverage-gap metadata. They are Python functions, not HTTP or agent tools yet.

The next phases will add a bounded agent that chooses follow-up queries, deterministic report verification, and a UI showing the timeline beside the tool trace and source excerpts.

## Offline checks

```sh
.venv/bin/python -m unittest discover -s backend/incident_investigation/tests -v
```

These tests inspect the fixture and query behavior without calling an LLM, Logfire, or external telemetry source.

## Boundaries and acceptance

No automated remediation or production telemetry access. Queries should be scoped by service and time, with bounded results and an explicit stop budget. The demo is sufficient when one known fixture yields a plausible cited report, one misleading correlation remains labeled as a hypothesis, and missing telemetry is disclosed instead of invented.
