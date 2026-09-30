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

Incident Investigation and Research & Workflow are runnable through the frontend. Incident Investigation has a synthetic fixture, scoped Python queries, a bounded investigator, citation checks, a backend API, and an engineer-review workspace. Simulations save their responses and workflow steps in `incident_simulation_outputs`, keyed by the shared `llm_runs` ID; the older alert-first route remains response-only. The other three directories hold design briefs and proposed contracts. Do not describe an incomplete system as a working end-to-end UI. See each system's `README.md` for its intended flow and acceptance bar; see the root `README.md` for the current portfolio map.

## How to extend a system

- Preserve a distinct architecture for each system. Implement the smallest demonstration that makes its central design decision visible in the UI and code.
- Keep model judgment inside explicit boundaries: typed inputs and outputs, scoped tools, bounded loops, deterministic authorization/action checks, and evidence or test results that a viewer can inspect.
- Run applicable cheap deterministic checks before every LLM or Jev call. Normalize and validate inputs, enforce schema, length, time, and scope limits, and use keyword or pattern checks on queries to catch obvious cases or provide signals for classification. Reject clearly invalid inputs before paying for a model call; send valid or ambiguous inputs and the relevant signals to the model for semantic judgment. After the model responds, apply deterministic thresholds, provenance checks, or action rules to its output. Do not treat a keyword match as proof of semantic relevance or safety. Show this order in architecture diagrams and workflow steps.
- Make the result reviewable. Show source locators and citations for knowledge work, tool steps where they explain decisions, test output and diffs for coding, and approval or escalation state for actions.
- Separate the execution walkthrough from the final decision. Lead the result with what triggered the run, observed impact, the proposed explanation, strongest evidence, and the key uncertainty; keep detailed tool steps expandable. State exactly what a reviewer approves or requests changes to.
- Freeze each agent's evidence scope at its trigger or request boundary. Verify that cited records were available and in scope, and distinguish this provenance check from proving that the model interpreted those records correctly. Label unverified causes as hypotheses.
- For every runnable demo, show the ordered workflow in the UI as it happens: request and scope, model inputs and visible decisions, tool calls with exact arguments and results, deterministic checks, persistence or action state, and the final stop reason. Keep the trace visible with the completed result; persist it when run history is part of that demo. Identify model private reasoning and provider internals as unavailable rather than inventing steps. A saved Logfire trace can supplement the UI, but it does not replace the in-app walkthrough.
- In the incident demo, the Run tab shows five expandable stages covering group members, candidate pass/fail decisions, Jev judgments, the agent tool loop, and verification. The complete step payload is persisted without a separate full-trace panel or duplicate tool-step panel.
- Use synthetic fixtures and mock services for new demos unless a real integration is essential to the architecture. Never use private repositories, real customer data, production telemetry, or external writes as demo fixtures.
- Keep documentation and status labels aligned with what actually runs. When a scaffold becomes runnable, update its README, the root README, and the frontend description together. State limits plainly; do not claim live quality, reliability, or production readiness based on mocked checks.
- Avoid adding a framework, agent, queue, or service solely for realism. Add complexity when it demonstrates a meaningful system boundary or failure mode.

## Implementation review workflow

Incident Investigation is complete as a portfolio demo; its phase history and limits are in `backend/incident_investigation/AGENTS.md`. For new systems, present a concrete Markdown phase plan with technical changes and verification criteria before implementing that phase. Approval of an overview does not approve each phase's details. After approval, implement only that phase, run relevant offline checks, and summarize the uncommitted changes for user review. Commit to `main` only after the user reviews and approves the implementation. Wait for that review before planning or starting the next phase. Track decisions and status in the system's `AGENTS.md`.

## Existing research demo

The research system is a FastAPI backend and React/Vite frontend. A deterministic query precheck validates and records keyword signals before Jev judges the request; application thresholds then decide the branch. A bounded single agent selects among filing search, financial data, and Tavily web search/extraction. Python resolves evidence IDs and source locators, checks grounding, performs at most one repair pass, and saves the briefing and diagnostics. The app owns the tool limits, evidence catalog, persistence, and final verification. Contracts are in `backend/research_workflow/contracts.py`; setup and known limits are in `backend/research_workflow/README.md`.

The frontend is in `frontend/`; the ASGI entry point is `backend.main:app`. Shared research data utilities are in `backend/shared/`. Backend dependencies are in `backend/requirements.txt` and frontend dependencies in `frontend/package-lock.json`.

`backend/.env` may contain `TAVILY_API_KEY` for research web search and extraction. No current incident tool uses it; incident evidence remains the synthetic telemetry fixture. Add other scoped web search tools only when a phase requires them.

## Verification

### Test AI systems by component before an end-to-end run

Do not use a user's paid live run as the first test of an agent change. Before asking
the user to run a system, verify each boundary independently with offline fixtures
and fake providers: input/fixture validation, deterministic filtering and grouping,
model adapter request and response shape, decision thresholds, tool arguments and
scoping, loop budgets and stop behavior, evidence verification, persistence, stream
events, and frontend run state. Then run a complete mocked workflow that uses a
realistic sequence of tool calls and provider-reported usage, not just a one-call
happy path. Cover at least one failure path and confirm the UI can explain it.
Use saved run records and Logfire traces to turn real failures into focused regression
cases. Report which checks used mocks, which interfaces were exercised, and any
remaining uncertainty before another live run. After the offline gate, run each
explicitly authorized live component smoke test separately, with bounded calls and
reported usage, before asking the user to pay for a full simulation.

Use offline checks for ordinary code changes. **Do not run real LLM calls during routine verification.** Explicitly named component smoke commands may call providers when the user authorizes them; run them one at a time and keep them out of unittest discovery and the default check commands. Do not run `backend/research_workflow/research_smoke.py` as part of routine verification; it starts a live provider/LLM workflow. Mock external providers in tests and report separately what has only been verified with mocks.

```sh
LOGFIRE_SEND_TO_LOGFIRE=false .venv/bin/python -m unittest discover -s backend/research_workflow/tests -v
cd frontend && npm run build && npm run lint && npm test
```

Run the relevant checks for changed code, plus `git diff --check`. If dependencies or local services are unavailable, say exactly which check could not run. Do not substitute live calls for missing offline coverage.

After editing Python files, apply the repository's Ruff save behavior to the changed files: `ruff check --fix <files>` followed by `ruff format <files>`. Then run `ruff check <files>` and `ruff format --check <files>` before requesting review.
