# Agent guide: AI Systems Architecture Demos

## Purpose

This repository is an interview portfolio for explaining five common AI system architectures. The goal is to make each system's request flow, model decisions, deterministic boundaries, evidence, and output easy to inspect and discuss. It is not a set of production applications. Favor a clear, credible end-to-end slice over feature breadth, infrastructure polish, or production hardening that does not help demonstrate the architecture.

The five systems are:

| System | Backend directory | Architectural focus |
| --- | --- | --- |
| Incident Investigation & Reporting | `backend/incident_investigation/` | Scoped telemetry queries, evidence-backed hypotheses, engineer review |
| Coding Agent for a Private Codebase | `backend/coding_agent/` | Code-aware discovery, isolated edit/test loop, reviewable diff |
| Internal Knowledge + Action | `backend/internal_knowledge_action/` | Access-controlled retrieval, cited answers, approval before actions |
| Customer Support | `backend/customer_support/` | Policy versus account state, checked actions, escalation |
| Research & Workflow | `backend/research_workflow/` | Autonomous source selection, cited findings, verification, saved run |

`backend/research_workflow/` is the only runnable system. The other four directories currently hold design briefs and proposed contracts, while their frontend pages are static architecture views. Do not describe a scaffold as an implemented agent or working API. See each system's `README.md` for its intended flow and acceptance bar; see the root `README.md` for the current portfolio map.

## How to extend a system

- Preserve a distinct architecture for each system. Implement the smallest demonstration that makes its central design decision visible in the UI and code.
- Keep model judgment inside explicit boundaries: typed inputs and outputs, scoped tools, bounded loops, deterministic authorization/action checks, and evidence or test results that a viewer can inspect.
- Make the result reviewable. Show source locators and citations for knowledge work, tool steps where they explain decisions, test output and diffs for coding, and approval or escalation state for actions.
- Use synthetic fixtures and mock services for new demos unless a real integration is essential to the architecture. Never use private repositories, real customer data, production telemetry, or external writes as demo fixtures.
- Keep documentation and status labels aligned with what actually runs. When a scaffold becomes runnable, update its README, the root README, and the frontend description together. State limits plainly; do not claim live quality, reliability, or production readiness based on mocked checks.
- Avoid adding a framework, agent, queue, or service solely for realism. Add complexity when it demonstrates a meaningful system boundary or failure mode.

## Existing research demo

The research system is a FastAPI backend and React/Vite frontend. A bounded single agent selects among filing search, financial data, and current news search/inspection. Python resolves evidence IDs and source locators, checks grounding, performs at most one repair pass, and saves the briefing and diagnostics. The app owns the tool limits, evidence catalog, persistence, and final verification. Its setup and known limits are in `backend/research_workflow/README.md`.

The frontend is in `frontend/`; the ASGI entry point is `backend.main:app`. Shared research data utilities are in `backend/shared/`. Backend dependencies are in `backend/requirements.txt` and frontend dependencies in `frontend/package-lock.json`.

## Verification

Use offline checks for ordinary code changes. **Do not run real LLM calls to test this app.** Do not run `backend/research_workflow/research_smoke.py` as part of routine verification; it starts a live provider/LLM workflow. Mock external providers in tests and report separately what has only been verified with mocks.

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/research_workflow/tests -v
cd frontend && npm run build && npm run lint
```

Run the relevant checks for changed code, plus `git diff --check`. If dependencies or local services are unavailable, say exactly which check could not run. Do not make external provider calls merely to prove an architecture demo works.
