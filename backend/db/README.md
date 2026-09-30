# Shared AI run registry

`llm_runs` provides a small identity and lifecycle record that any of the five AI-system demos can use. One row represents a top-level system execution. The UUID is the application run ID; `logfire_trace_id` is an optional 32-character OpenTelemetry trace ID for viewing execution in Logfire when export is enabled. It remains null when export is disabled. The table does not store prompts, tool output, evidence, reports, or provider-call history.

The schema is defined by `LlmRun` in `schemas.py` and the explicit PostgreSQL migration `migrations/004_create_llm_runs.sql`. For a new database, `db_utils.init_db()` creates it with the other ORM tables. For an existing database, apply migration 004 explicitly; `create_all()` does not alter existing tables. Migration 004 was applied to this checkout's configured Neon database on 2026-09-29.

`llm_runs.py` supplies transaction-scoped helpers. The caller creates and commits the session, then moves a run through `pending -> running -> completed` or `pending/running -> failed`. Conditional updates reject repeated or conflicting terminal transitions. `system_key` identifies the owning demo, and an optional supplied UUID allows a domain-specific row to share the same ID. The helpers do not retry failed transactions or assume a worker exists.

Research & Workflow now creates a shared `llm_runs` row and a `research_runs` row with the same ID in one transaction. Its own row stores the briefing, verification, usage, and checkpoint; `research_run_steps` stores ordered public workflow steps. A failed checkpoint remains failed, while a resumed attempt gets a new shared ID linked by `resumed_from_run_id`. Migration `migrations/006_research_shared_runs_and_steps.sql` backfills existing research IDs into `llm_runs`, adds the links, and creates the step table. It was verified twice on a disposable local PostgreSQL database with a seeded old run. It was applied to this checkout's configured Neon database on 2026-09-30: all 15 existing research rows link to the correct system, both foreign keys exist, and the step table is present. Other existing databases still need the migration applied explicitly.

The Incident Investigation API creates and updates a shared run row. A simulation creates one top-level row even if no incident is found; a triggered investigation reuses that ID. `incident_simulation_outputs` stores the full simulation response, including classifier judgments, reports, and workflow steps, keyed by that ID. The table is defined in `schemas.py` and migration `migrations/005_create_incident_simulation_outputs.sql`. Apply migration 005 to other existing databases before running the updated simulation API; `create_all()` only covers a new database. Migration 005 was applied to this checkout's configured Neon database on 2026-09-29. The older alert-first route remains response-only.

Offline test:

```sh
.venv/bin/python -m unittest discover -s backend/db/tests -v
```
