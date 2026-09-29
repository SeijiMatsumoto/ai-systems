# AI Systems Architecture Demos

This repository is an interview-oriented set of five common AI system designs. Each system has a distinct request flow, output contract, and boundary between model judgment and deterministic application code. The emphasis is on explaining and inspecting architecture, not building five production services.

| System | Demonstrates | Status |
| --- | --- | --- |
| [Incident Investigation](backend/incident_investigation/README.md) | Bounded telemetry queries, evidence-backed hypotheses, engineer review | Architecture scaffold |
| [Coding Agent](backend/coding_agent/README.md) | Code-aware context, isolated edit/test loop, reviewable diff | Architecture scaffold |
| [Internal Knowledge + Action](backend/internal_knowledge_action/README.md) | ACL-aware retrieval, cited answers, approval before actions | Architecture scaffold |
| [Customer Support](backend/customer_support/README.md) | Policy and account separation, action checks, escalation | Architecture scaffold |
| [Research & Workflow](backend/project_02_research_briefing_system/README.md) | Autonomous source selection, cited findings, verification, saved run | Runnable local demo |

The four scaffolds contain design briefs and proposed typed request/output contracts. They have no API routes, agents, provider calls, or executable workflows yet. The React workbench presents their architecture and clearly labels them as scaffolds. The research system is the only runnable application.

## Research demo

A user asks a question about a public company. The backend gets a company snapshot and price history, then one bounded agent chooses among stored filing search, historical financials, and live news search and inspection. It returns findings that reference evidence IDs. Application code resolves those IDs, checks source locators, runs a bounded grounding and repair pass, and saves the briefing and run diagnostics. The React UI shows citations, verification state, and recent runs.

[Research architecture and local setup](backend/project_02_research_briefing_system/README.md)

## Offline checks

These checks use mocks and do not run an agent or call an LLM:

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/project_02_research_briefing_system/tests -v
cd frontend && npm run build && npm run lint
```

The local environment used for the research demo is Python 3.13. Backend direct dependencies are listed in `backend/requirements.txt`; frontend dependencies are in `frontend/package-lock.json`.

## Scope

This is an architecture portfolio. The research demo does not provide user authentication, source-level access control, human approval actions, or a representative evaluation benchmark. A live research run requires external providers and local infrastructure. Offline checks do not establish live provider behavior or generated briefing quality.
