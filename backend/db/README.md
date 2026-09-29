# Shared AI run registry

`llm_runs` provides a small identity and lifecycle record that any of the five AI-system demos can use. One row represents a top-level system execution. The UUID is the application run ID; `logfire_trace_id` is an optional 32-character OpenTelemetry trace ID for viewing execution in Logfire. The table does not store prompts, tool output, evidence, reports, or provider-call history.

The schema is defined by `LlmRun` in `schemas.py` and the explicit PostgreSQL migration `migrations/004_create_llm_runs.sql`. For a new local database, `db_utils.init_db()` creates it with the other ORM tables. For an existing database, apply migration 004 explicitly; `create_all()` does not alter existing tables. The migration has not been applied to a live database as part of this phase.

`llm_runs.py` supplies transaction-scoped helpers. The caller creates and commits the session, then moves a run through `pending -> running -> completed` or `pending/running -> failed`. Conditional updates reject repeated or conflicting terminal transitions. `system_key` identifies the owning demo, and an optional supplied UUID allows a domain-specific row to share the same ID. The helpers do not retry failed transactions or assume a worker exists.

The current research demo still uses `research_runs` for its own lifecycle; this phase does not backfill or change that workflow. **Follow-up:** revisit Research & Workflow and connect its runs to this shared registry, including existing-run migration or backfill. Incident Investigation will start using the registry in Phase 2B. Until then, this is an available schema and library, not an active cross-system run history.

Offline test:

```sh
.venv/bin/python -m unittest discover -s backend/db/tests -v
```
