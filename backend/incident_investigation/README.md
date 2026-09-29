# Incident Investigation & Reporting Agent

**Status:** architecture scaffold. There is no API, agent, telemetry store, or live incident execution yet.

## Demo contract

- **Input:** a service, alert ID, and investigation time window over synthetic logs, metrics, traces, and deployment records.
- **Output:** a cited incident timeline, separated facts/correlations/hypotheses, likely causes, unknowns, and a report for engineer review. The proposed data shape is in `contracts.py`.
- **Dominant design decision:** telemetry query services narrow large data before the model sees it. The model investigates and synthesizes; it is not the telemetry source of truth.

## Intended flow

```text
Alert + time window -> deterministic telemetry queries -> bounded evidence set
                   -> investigation loop -> cited claims -> engineer review
```

The first runnable slice should use a versioned synthetic incident fixture with an error spike and a nearby deployment. Read-only tools should search logs, aggregate metrics, fetch trace spans, and list deployments by service and time. A bounded agent can choose follow-up queries. The verifier must reject any report claim without a resolvable evidence ID. The UI should show the timeline beside the tool trace and source excerpts.

## Boundaries and acceptance

No automated remediation or production telemetry access. Queries should be scoped by service and time, with bounded results and an explicit stop budget. The demo is sufficient when one known fixture yields a plausible cited report, one misleading correlation remains labeled as a hypothesis, and missing telemetry is disclosed instead of invented.
