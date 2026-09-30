# Research Briefing Agent

## Demo contract

**Input:** a public-company symbol, timezone-aware `as_of` timestamp, research question, audience, and time horizon.

**Output:** a saved `ResearchBriefing` with an executive summary, findings with source evidence, outlook, limitations, and a `VerificationResult`. The UI exposes the cited passages and financial values alongside the run's verification and trace metadata.

**Design question:** when should a research agent choose another source, and how can the application keep its final claims tied to exact evidence?

## Request flow

```mermaid
flowchart TD
    UI[React research workspace] --> API[FastAPI request and run state]
    API --> Q[Query classifier]
    Q --> P[Company identity and prior-day price context]
    P --> A[One bounded research agent]
    A --> F[Stored SEC filing search]
    A --> Y[Current Yahoo financial statements]
    A --> S[Tavily web search: discovery]
    S --> E[Tavily extract: selected URLs]
    F --> C[Run-scoped evidence catalog]
    Y --> C
    E --> C
    C --> D[Draft findings with evidence IDs]
    D --> V[Source checks and grounding; one repair]
    V --> R[research_runs: briefing, checks, checkpoint]
    API --> L[llm_runs: shared ID and lifecycle]
    R --> W[research_run_steps: ordered workflow]
    W --> SSE[Saved API and SSE stream]
    SSE --> UI
    R --> UI
```

The agent uses a tool loop because source selection depends on intermediate results. The application owns the request schema, allowed tools, step and time budgets, evidence catalog, database writes, and final verification. It does not use multiple research agents or an application-managed planning queue.

### Evidence and sources

- SEC filings are explicitly loaded through the filing setup panel, chunked, embedded, and searched with metadata filters. This setup uses external services; it is not part of the offline test run.
- Yahoo Finance supplies company identity, daily close prices, and current financial statements. Mutable snapshot metrics are not citable; daily prices on the `as_of` date are excluded. The financial statement tool declines historical `as_of` requests because the provider's current view cannot establish what was available then.
- Tavily Search supplies dated discovery metadata for bounded company-scoped news or general web queries. Undated, later-than-`as_of`, and wrong-company results are excluded. The agent must extract selected URLs before citing them. Extraction stores exact passages and registers citable evidence IDs. Publication dates are provider estimates and extracted content is the current page, so historical availability is not proven.
- The model chooses evidence IDs but does not author source metadata. Python hydrates the final output from the run-scoped evidence catalog and verifies document offsets, company and publication scope, and financial field paths. Request, tool, provider, evidence, and output contracts live in `contracts.py`.

A grounding classifier checks each finding. A rejected finding receives at most one repair attempt; findings that still fail are excluded. The summary and outlook are rebuilt from retained findings and checked again, with deterministic fallbacks. `approval_ready` describes automated checks; there is no implemented human approve/reject workflow.

### State and limits

Research attempts share their UUID and lifecycle with `llm_runs`. `research_runs` saves the request, briefing, verification, usage, model/prompt/tool versions, trace ID, and checkpoint. Ordered `research_run_steps` include model-visible inputs, tool arguments and results, verification decisions, checkpoint writes, and stop reason. `POST /agent/research_brief/stream` emits each step after persistence and then emits the final result or error. `GET /research-runs/{id}` returns the saved steps. The current UI does not yet display this sequence.

The request fingerprint includes the full `as_of` instant and workflow versions. The workflow has a 180-second timeout and concurrency limit; the agent has a 120-second timeout and request, tool-call, and token limits. A failed run can resume from the post-agent checkpoint as a **new linked attempt**; the failed attempt remains terminal. These controls demonstrate the shape of a bounded workflow, not a guarantee of live reliability.

Follow-up for the portfolio-wide demo requirement: render the saved and streamed steps in the research UI alongside the briefing. The current UI shows the briefing, evidence, verification, and trace metadata, but not the step sequence.

## Local development

Use Python 3.13, PostgreSQL with the `vector` extension, and the dependencies in `backend/requirements.txt`. Set `DATABASE_URL`, `OPENAI_API_KEY`, and `TAVILY_API_KEY` in `backend/.env`. Create a fresh database schema with `backend.db.db_utils.init_db()` after enabling `vector`. For an existing database, apply `backend/db/migrations/006_research_shared_runs_and_steps.sql` after migrations 001–004; `create_all()` does not alter existing tables. Migration 006 has been checked on a disposable database but has **not** been applied to this checkout's configured database. The UI also needs Node and the dependencies in `frontend/package-lock.json`. See the [root README](../../README.md#run-the-backend-locally) for setup.

```sh
# From the repository root, after dependencies and services are ready:
python -m uvicorn backend.main:app --reload
cd frontend && npm ci && npm run dev
```

The UI uses `http://127.0.0.1:8000` by default. Filing setup is in the Admin view. News is discovered during a run, so it does not need a separate backfill. The `research_smoke.py` script is a **live** run and uses external providers and LLM calls; it is intentionally excluded from offline verification.

## Offline verification

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/research_workflow/tests -v
cd frontend && npm run build && npm run lint
```

Tests mock provider calls and cover evidence contracts, Tavily filtering and extraction, agent tool responses, a multi-tool fake-model agent run, shared run lifecycle, failed-checkpoint resume, saved step order, SSE order, and request/cache boundaries. They do not establish live provider behavior or briefing quality. There is no representative end-to-end evaluation set yet.

## Demo limits

This is a local architecture demonstration. It lacks authentication, source-level access control, human approval actions, a durable worker queue, and measured quality/latency/cost evaluations. Tavily date estimates and current-page extraction cannot prove historical page content. Provider failures and data quality can still prevent a successful briefing. The UI renders structured briefing fields and evidence directly rather than exporting Markdown.
