# AI Systems Architecture Demos

This repository is an interview-oriented set of five common AI system designs. Each system has a distinct request flow, output contract, and boundary between model judgment and deterministic application code. The emphasis is on explaining and inspecting architecture, not building five production services.

| System | Demonstrates | Status |
| --- | --- | --- |
| [Incident Investigation](backend/incident_investigation/README.md) | Bounded telemetry queries, evidence-backed hypotheses, engineer review | Runnable backend API; frontend pending |
| [Coding Agent](backend/coding_agent/README.md) | Code-aware context, isolated edit/test loop, reviewable diff | Architecture scaffold |
| [Internal Knowledge + Action](backend/internal_knowledge_action/README.md) | ACL-aware retrieval, cited answers, approval before actions | Architecture scaffold |
| [Customer Support](backend/customer_support/README.md) | Policy and account separation, action checks, escalation | Architecture scaffold |
| [Research & Workflow](backend/research_workflow/README.md) | Autonomous source selection, cited findings, verification, saved run | Runnable local demo |

Incident Investigation has a synthetic telemetry fixture, scoped Python queries, a bounded investigator, citation checks, and a backend API. Its frontend remains an architecture view. The other three scaffolds contain design briefs and proposed typed request/output contracts. Research & Workflow is the only runnable application through the UI.

## Run the backend locally

Run these commands from the repository root. You need Python 3.13 and a local PostgreSQL database with the `vector` extension installed. The ASGI app exposes both the research API and `POST /agent/incident_investigation`.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
createdb ai_systems
psql -d ai_systems -c 'CREATE EXTENSION IF NOT EXISTS vector;'
cp -n backend/.env.example backend/.env
```

Edit `backend/.env` with your PostgreSQL credentials in `DATABASE_URL`. Set `OPENAI_API_KEY` and `WORLD_NEWS_API_KEY` before running a live research briefing; `/docs` and offline tests do not need provider calls. To export traces, set `LOGFIRE_API_KEY` to a project API key with **Send telemetry** permission (or use `LOGFIRE_TOKEN`) and set `LOGFIRE_SEND_TO_LOGFIRE=true`. The example disables export by default. Offline test commands below override export to `false`.

For a **new** database, create the ORM tables, then start FastAPI:

```sh
.venv/bin/python -c 'from backend.db.db_utils import init_db; init_db()'
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` to inspect the API. For an **existing** database, apply any missing SQL files in `backend/db/migrations/` in numeric order; `init_db()` does not alter existing tables. In particular, migration `004_create_llm_runs.sql` adds the shared run registry. Filing setup uses the API's ingestion route or the frontend Admin view and makes external provider calls.

The incident route accepts `service=checkout`, `alert_id=alert-0001`, and an investigation window within the fixture's `2026-04-14T14:00:00Z` to `2026-04-14T14:59:00Z` range. It runs the configured model if called normally; the offline checks below use a fake model.

To run the frontend as well, use a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

The frontend defaults to `http://127.0.0.1:8000` for the backend.

## Research demo

A user asks a question about a public company. The backend gets a company snapshot and price history, then one bounded agent chooses among stored filing search, historical financials, and live news search and inspection. It returns findings that reference evidence IDs. Application code resolves those IDs, checks source locators, runs a bounded grounding and repair pass, and saves the briefing and run diagnostics. The React UI shows citations, verification state, and recent runs.

[Research architecture and local setup](backend/research_workflow/README.md)

## Offline checks

These checks use mocked providers and a local fake model for the incident agent. They do not make external LLM calls:

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/research_workflow/tests -v
.venv/bin/python -m unittest discover -s backend/db/tests -v
.venv/bin/python -m unittest discover -s backend/incident_investigation/tests -v
cd frontend && npm run build && npm run lint
```

The local environment used for the research demo is Python 3.13. Backend direct dependencies are listed in `backend/requirements.txt`; frontend dependencies are in `frontend/package-lock.json`.

The shared [`llm_runs` schema](backend/db/README.md) holds cross-system run IDs, lifecycle state, and an optional Logfire trace ID. The local incident investigator uses it for ID and state, and saves its trace ID when Logfire export is enabled. Research & Workflow integration with `llm_runs` remains follow-up work.

## Scope

This is an architecture portfolio. The research demo does not provide user authentication, source-level access control, human approval actions, or a representative evaluation benchmark. A live research run requires external providers and local infrastructure. Offline checks do not establish live provider behavior or generated briefing quality.
