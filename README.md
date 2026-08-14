# AI Systems Portfolio

This repository is a hands-on portfolio of AI systems built to explore different agent architectures, reliability patterns, and product domains. It is maintained by an AI engineer with more than two years of experience building production software and AI workflows in a hedge-fund environment.

The goal is not to repeat the same chatbot or RAG wrapper across several demos. Each project is intended to make a different system-design problem concrete: multi-agent coordination, tool use, planning, evaluation, long-running workflows, human approval, memory, observability, or safe action-taking.

## Projects

| # | System | Primary design focus | Status |
|---|---|---|---|
| 01 | [Automated Trading Strategy Backtester](backend/project_01_automated_trading_strategy_backtester/) | Code generation, sandboxed execution, and repair loops | Planned |
| 02 | [Agentic Research & Briefing System](backend/project_02_research_briefing_system/) | Evidence-grounded research, tool orchestration, and human review | In progress |
| 03 | [Continuous Portfolio Risk Sentinel](backend/project_03_continuous_portfolio_risk_sentinel/) | Long-running monitoring, memory, and escalation | Planned |
| 04 | [Client Meeting Prep & Follow-Up Agent](backend/project_04_client_meeting_prep_follow_up_agent/) | Workflow orchestration and action tracking | Planned |
| 05 | [Regulatory Change Impact Simulator](backend/project_05_regulatory_change_impact_simulator/) | RAG, impact analysis, and approval gates | Planned |
| 06 | [Autonomous Incident Response Coordinator](backend/project_06_autonomous_incident_response_coordinator/) | Multi-agent diagnosis and controlled remediation | Planned |
| 07 | [Personalized Financial Wellness Coach](backend/project_07_personalized_financial_wellness_coach/) | Long-term memory and adaptive planning | Planned |
| 08 | [Cross-Team Knowledge Synthesis](backend/project_08_cross_team_knowledge_synthesis_decision_support/) | Continual synthesis, conflict detection, and knowledge graphs | Planned |
| 09 | [Vendor Contract Negotiation Assistant](backend/project_09_vendor_contract_negotiation_assistant/) | Scenario analysis and human-in-the-loop iteration | Planned |
| 10 | [Adaptive Fraud Pattern Hunter](backend/project_10_adaptive_fraud_pattern_hunter/) | Hypothesis generation, testing, and promotion gates | Planned |
| 11 | [Goal-Driven Productivity Agent](backend/project_11_goal_driven_personal_productivity_agent/) | Goal decomposition, tool use, and replanning | Planned |

## Repository Structure

- `backend/`: Individual system implementations plus shared data and model utilities.
- `frontend/`: The user interface for exercising and inspecting the systems.
- `project_ideas.md`: The original problem statements behind the portfolio.

Each project README documents its problem, intended architecture, constraints, and execution instructions as the implementation develops. Status labels describe what is present in this repository today; planned projects are design targets, not claims of completed production systems.

## What This Portfolio Demonstrates

The work emphasizes decisions that matter after a prototype: explicit agent responsibilities, typed state and tool contracts, source provenance, deterministic validation, evaluation datasets, failure handling, cost and latency controls, human approval boundaries, and traces that explain why a run produced its result.

Financial use cases in this repository are educational demonstrations built from public or synthetic data. They are not investment advice and do not contain proprietary employer information.
