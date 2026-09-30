# AI Systems Architecture Demos

This repository is an interview-oriented set of five common AI system designs. Each system has a distinct request flow, output contract, and boundary between model judgment and deterministic application code. The emphasis is on explaining and inspecting architecture, not building five production services.

| System | Demonstrates | Status |
| --- | --- | --- |
| [Incident Investigation](backend/incident_investigation/README.md) | Bounded telemetry queries, evidence-backed hypotheses, engineer review | Runnable local demo |
| [Coding Agent](backend/coding_agent/README.md) | Code-aware context, isolated edit/test loop, reviewable diff | Architecture scaffold |
| [Internal Knowledge + Action](backend/internal_knowledge_action/README.md) | ACL-aware retrieval, cited answers, approval before actions | Architecture scaffold |
| [Customer Support](backend/customer_support/README.md) | Policy and account separation, action checks, escalation | Architecture scaffold |
| [Research & Workflow](backend/research_workflow/README.md) | Autonomous source selection, cited findings, verification, saved run | Runnable local demo |

Incident Investigation and Research & Workflow are runnable through the frontend. Incident Investigation uses a synthetic telemetry fixture, scoped Python queries, a bounded investigator, citation checks, and an engineer-review workspace. The UI streams ordered harness steps, including model context, tool inputs and outputs, verification, and run state. Its report and execution trace are available only in the immediate response; the shared registry saves the run ID and status. The other three systems remain architecture scaffolds.

Every system's demo should expose its full workflow in the UI, including inputs, model choices, tool arguments and results, checks, and final state. The incident demo now streams these steps. Research & Workflow currently shows results, evidence, verification, and trace metadata but needs a fuller in-app execution timeline; that is follow-up work, not current functionality.

## Run the backend locally

This checkout already has the Python environment, `backend/.env`, and database schema set up. Start the API with one command from `backend/`:

```sh
cd backend
./run
```

Open `http://127.0.0.1:8000/docs`. The launcher uses the repo's `.venv`, loads `backend/.env`, and reloads on backend code changes. The ASGI app exposes the research API plus final-response and streaming incident routes. Calling an agent route normally uses its configured model; opening `/docs` does not.

For a fresh clone on another machine, complete one-time setup from the repository root:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
.venv/bin/python -c 'from backend.db.db_utils import init_db; init_db()'
```

Set `DATABASE_URL` in the new `backend/.env` before running `init_db()`. A new database needs PostgreSQL with the `vector` extension; an existing database needs the missing checked-in migrations instead of `init_db()`. Live research briefings need `OPENAI_API_KEY` and `WORLD_NEWS_API_KEY`. To export traces, set a telemetry-write `LOGFIRE_API_KEY` (or `LOGFIRE_TOKEN`) and enable `LOGFIRE_SEND_TO_LOGFIRE`. The example disables export by default. Filing setup through the API or Admin view makes external provider calls.

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
