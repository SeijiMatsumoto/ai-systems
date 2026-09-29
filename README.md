# AI Systems Architecture Demos

This repository is an interview-oriented set of five common AI system designs. Each system has a distinct request flow, output contract, and boundary between model judgment and deterministic application code. The emphasis is on explaining and inspecting architecture, not building five production services.

| System | Demonstrates | Status |
| --- | --- | --- |
| [Incident Investigation](backend/incident_investigation/README.md) | Bounded telemetry queries, evidence-backed hypotheses, engineer review | Synthetic fixture + query layer |
| [Coding Agent](backend/coding_agent/README.md) | Code-aware context, isolated edit/test loop, reviewable diff | Architecture scaffold |
| [Internal Knowledge + Action](backend/internal_knowledge_action/README.md) | ACL-aware retrieval, cited answers, approval before actions | Architecture scaffold |
| [Customer Support](backend/customer_support/README.md) | Policy and account separation, action checks, escalation | Architecture scaffold |
| [Research & Workflow](backend/research_workflow/README.md) | Autonomous source selection, cited findings, verification, saved run | Runnable local demo |

Incident Investigation has a synthetic telemetry fixture and scoped Python queries, but no agent or API yet. The other three scaffolds contain design briefs and proposed typed request/output contracts. None of those four systems has an executable end-to-end workflow or frontend interaction yet. The React workbench presents their architecture as planned. Research & Workflow is the only runnable application.

## Research demo

A user asks a question about a public company. The backend gets a company snapshot and price history, then one bounded agent chooses among stored filing search, historical financials, and live news search and inspection. It returns findings that reference evidence IDs. Application code resolves those IDs, checks source locators, runs a bounded grounding and repair pass, and saves the briefing and run diagnostics. The React UI shows citations, verification state, and recent runs.

[Research architecture and local setup](backend/research_workflow/README.md)

## Offline checks

These checks use mocks and do not run an agent or call an LLM:

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/research_workflow/tests -v
.venv/bin/python -m unittest discover -s backend/incident_investigation/tests -v
cd frontend && npm run build && npm run lint
```

The local environment used for the research demo is Python 3.13. Backend direct dependencies are listed in `backend/requirements.txt`; frontend dependencies are in `frontend/package-lock.json`.

The shared [`llm_runs` schema](backend/db/README.md) is available for cross-system run IDs, lifecycle state, and optional Logfire trace IDs. It is not yet wired into an agent workflow.

## Scope

This is an architecture portfolio. The research demo does not provide user authentication, source-level access control, human approval actions, or a representative evaluation benchmark. A live research run requires external providers and local infrastructure. Offline checks do not establish live provider behavior or generated briefing quality.
