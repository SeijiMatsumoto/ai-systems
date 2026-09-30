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

Incident Investigation and Research & Workflow are runnable through the frontend. Incident Investigation has a synthetic fixture, scoped Python queries, a bounded investigator, citation checks, a backend API, and an engineer-review workspace. Its report is response-only. The other three directories hold design briefs and proposed contracts. Do not describe an incomplete system as a working end-to-end UI. See each system's `README.md` for its intended flow and acceptance bar; see the root `README.md` for the current portfolio map.

## How to extend a system

- Preserve a distinct architecture for each system. Implement the smallest demonstration that makes its central design decision visible in the UI and code.
- Keep model judgment inside explicit boundaries: typed inputs and outputs, scoped tools, bounded loops, deterministic authorization/action checks, and evidence or test results that a viewer can inspect.
- Make the result reviewable. Show source locators and citations for knowledge work, tool steps where they explain decisions, test output and diffs for coding, and approval or escalation state for actions.
- For every runnable demo, show the ordered workflow in the UI as it happens: request and scope, model inputs and visible decisions, tool calls with exact arguments and results, deterministic checks, persistence or action state, and the final stop reason. Keep the trace visible with the completed result; persist it when run history is part of that demo. Identify model private reasoning and provider internals as unavailable rather than inventing steps. A saved Logfire trace can supplement the UI, but it does not replace the in-app walkthrough.
- Use synthetic fixtures and mock services for new demos unless a real integration is essential to the architecture. Never use private repositories, real customer data, production telemetry, or external writes as demo fixtures.
- Keep documentation and status labels aligned with what actually runs. When a scaffold becomes runnable, update its README, the root README, and the frontend description together. State limits plainly; do not claim live quality, reliability, or production readiness based on mocked checks.
- Avoid adding a framework, agent, queue, or service solely for realism. Add complexity when it demonstrates a meaningful system boundary or failure mode.

## Current incident implementation flow

The user approved a five-phase plan for `backend/incident_investigation/`. Approval of the overview does not approve each phase's details. Before each phase, present a concrete Markdown implementation plan with technical changes and verification criteria, then wait for approval. After approval, implement only that phase, run relevant offline checks, and summarize the uncommitted changes for user review. Commit to `main` only after the user reviews and approves the implementation. Wait for that review before planning or starting the next phase. Track decisions and status in `backend/incident_investigation/AGENTS.md`.

## Existing research demo

The research system is a FastAPI backend and React/Vite frontend. A bounded single agent selects among filing search, financial data, and current news search/inspection. Python resolves evidence IDs and source locators, checks grounding, performs at most one repair pass, and saves the briefing and diagnostics. The app owns the tool limits, evidence catalog, persistence, and final verification. Its setup and known limits are in `backend/research_workflow/README.md`.

The frontend is in `frontend/`; the ASGI entry point is `backend.main:app`. Shared research data utilities are in `backend/shared/`. Backend dependencies are in `backend/requirements.txt` and frontend dependencies in `frontend/package-lock.json`.

`backend/.env` may contain `TAVILY_API_KEY` for future agents that need web search. No current incident tool uses it; incident evidence remains the synthetic telemetry fixture. The existing research news tool uses World News API. Add a scoped web search tool only when a phase requires it.

## Verification

Use offline checks for ordinary code changes. **Do not run real LLM calls to test this app.** Do not run `backend/research_workflow/research_smoke.py` as part of routine verification; it starts a live provider/LLM workflow. Mock external providers in tests and report separately what has only been verified with mocks.

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/research_workflow/tests -v
cd frontend && npm run build && npm run lint
```

Run the relevant checks for changed code, plus `git diff --check`. If dependencies or local services are unavailable, say exactly which check could not run. Do not make external provider calls merely to prove an architecture demo works.

After editing Python files, apply the repository's Ruff save behavior to the changed files: `ruff check --fix <files>` followed by `ruff format <files>`. Then run `ruff check <files>` and `ruff format --check <files>` before requesting review.
