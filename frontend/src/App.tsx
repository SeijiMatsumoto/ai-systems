import { useState, useEffect, useRef } from 'react';

interface Project {
  id: string;
  number: string;
  title: string;
  category: string;
  problem: string;
  outcome: string;
  backendPort: number;
  status: 'Not Started' | 'Running' | 'Completed' | 'Error';
  apiPath: string;
  defaultInput: string;
  inputLabel: string;
  inputPlaceholder: string;
}

const PROJECTS: Project[] = [
  {
    id: 'backtester',
    number: '01',
    title: 'Automated Trading Strategy Backtester',
    category: 'Finance',
    problem: 'Quantitative researchers spend hours translating investment ideas into Python backtesting code (e.g., using libraries like Pandas or Backtrader). They often waste time fixing syntax errors, handling missing data, or adjusting parameters to make the script run.',
    outcome: 'A web app where a user describes a trading strategy in plain English, and an agent compiles the script, executes it, self-corrects any code tracebacks, and returns Sharpe ratios and backtest charts.',
    backendPort: 8001,
    status: 'Not Started',
    apiPath: 'api/backtest',
    defaultInput: 'Buy AAPL when the 50-day moving average crosses above the 200-day moving average, and sell when it crosses below. Start with $100,000.',
    inputLabel: 'Strategy Prompt',
    inputPlaceholder: 'Describe your trading strategy...'
  },
  {
    id: 'researcher',
    number: '02',
    title: 'Multi-Agent Research & Briefing System',
    category: 'Finance / Client-Facing',
    problem: 'Analysts and clients spend hours piecing together fragmented market, company, and regulatory information from filings, news, and internal notes.',
    outcome: 'An agent team that autonomously plans research, retrieves and synthesizes information (RAG over proprietary + public sources), debates findings, and produces a polished, cited briefing that a human can approve or refine before delivery.',
    backendPort: 8002,
    status: 'Not Started',
    apiPath: 'api/research',
    defaultInput: 'Briefing on Nvidia (NVDA) Q2 growth, recent regulatory scrutiny, and competitor chip launches (AMD/Intel).',
    inputLabel: 'Research Subject / Prompt',
    inputPlaceholder: 'Enter company, industry, or regulatory subject to research...'
  },
  {
    id: 'risk_sentinel',
    number: '03',
    title: 'Continuous Portfolio Risk Sentinel',
    category: 'Finance / Internal Ops',
    problem: 'Risk teams are flooded with alerts and struggle to distinguish noise from material emerging risks across positions, counterparties, and market regimes.',
    outcome: 'A looping agent that continuously monitors data streams, maintains memory of prior risk theses, runs scenario probes, escalates only high-conviction issues, and requests human judgment (HITL) when uncertainty or policy thresholds are crossed.',
    backendPort: 8003,
    status: 'Not Started',
    apiPath: 'api/risk',
    defaultInput: 'Monitor US High Yield Bond Portfolio for exposure to regional banking credit spread spikes.',
    inputLabel: 'Portfolio / Asset Scope',
    inputPlaceholder: 'Define portfolio positions or risk parameters to monitor...'
  },
  {
    id: 'reg_change',
    number: '04',
    title: 'Regulatory Change Impact Simulator',
    category: 'Compliance',
    problem: 'New rules arrive frequently; mapping them to existing products, processes, and controls is slow and error-prone.',
    outcome: 'An agent that ingests regulatory text (RAG), maps obligations to the firm’s inventory, simulates downstream process and system impacts, proposes control changes, and routes high-impact items for human sign-off before any implementation.',
    backendPort: 8004,
    status: 'Not Started',
    apiPath: 'api/compliance',
    defaultInput: 'Analyze the impact of the SEC Rule 10b-5 amendments on insider trading compliance for cross-border equities.',
    inputLabel: 'Regulation Document / Rule',
    inputPlaceholder: 'Enter regulation text or rule reference...'
  },
  {
    id: 'incident_coordinator',
    number: '05',
    title: 'Autonomous Incident Response Coordinator',
    category: 'Internal / Ops',
    problem: 'Production incidents require rapid triage across logs, metrics, recent changes, and on-call knowledge, often with incomplete context.',
    outcome: 'A multi-agent system that detects anomalies, gathers evidence, hypothesizes root causes, proposes and (with HITL gates) executes remediation steps, updates runbooks, and generates a post-mortem draft.',
    backendPort: 8005,
    status: 'Not Started',
    apiPath: 'api/incident',
    defaultInput: 'CRITICAL: Database connection pool exhaustion detected in billing-service-prod.',
    inputLabel: 'Incident Log / Alert',
    inputPlaceholder: 'Paste incident webhook data or error messages...'
  },
  {
    id: 'financial_wellness',
    number: '06',
    title: 'Personalized Financial Wellness Coach',
    category: 'Consumer / External',
    problem: 'Retail users struggle to turn scattered financial data and goals into coherent, adaptive plans that evolve with life events.',
    outcome: 'An agent that maintains long-term memory of the user’s situation, retrieves relevant knowledge, plans multi-step strategies (budgeting, debt, investing), checks in periodically, adapts when new data arrives, and surfaces decisions for user confirmation.',
    backendPort: 8006,
    status: 'Not Started',
    apiPath: 'api/coach',
    defaultInput: 'User: John, 34. Goal: Buy a home in 3 years with $40k down. Debt: $12k student loans at 4.5%. Income: $85k.',
    inputLabel: 'User Goal Profile',
    inputPlaceholder: 'Enter age, income, debts, and key financial goals...'
  },
  {
    id: 'knowledge_synthesis',
    number: '07',
    title: 'Cross-Team Knowledge Synthesis & Decision Support',
    category: 'Internal Ops',
    problem: 'Critical institutional knowledge is siloed across teams; decision-makers lack a living synthesis that updates as new information appears.',
    outcome: 'A looping agent that continuously crawls internal sources (RAG), identifies emerging themes and conflicts, maintains a living knowledge graph of key decisions and rationales, and proactively briefs stakeholders while flagging areas that need human resolution.',
    backendPort: 8007,
    status: 'Not Started',
    apiPath: 'api/knowledge',
    defaultInput: 'Crawl project-alpha and project-beta folders to detect API deprecation conflicts.',
    inputLabel: 'Data Sources / Scope',
    inputPlaceholder: 'Specify directories, Slack channels, or document buckets to sync...'
  },
  {
    id: 'vendor_negotiator',
    number: '08',
    title: 'Vendor & Contract Negotiation Assistant',
    category: 'Internal Procurement',
    problem: 'Negotiations drag because historical terms, market benchmarks, risk clauses, and internal preferences are hard to surface and reconcile in real time.',
    outcome: 'An agent that retrieves prior contracts and playbooks (RAG), models negotiation scenarios, drafts clause alternatives, tracks counterparty responses, and loops with the human negotiator until terms are acceptable or escalated.',
    backendPort: 8008,
    status: 'Not Started',
    apiPath: 'api/negotiate',
    defaultInput: 'Contract: SaaS subscription renewal with Datadog. Rate hike: 8%. Preferred maximum: 5%.',
    inputLabel: 'Negotiation Goal',
    inputPlaceholder: 'Enter vendor, renewal contract terms, and company limits...'
  },
  {
    id: 'fraud_hunter',
    number: '09',
    title: 'Adaptive Fraud Pattern Hunter',
    category: 'Risk / Compliance',
    problem: 'Static rules and simple models lag behind evolving fraud tactics; investigators drown in false positives.',
    outcome: 'An agent that explores transaction and behavioral data, proposes and tests new pattern hypotheses in a sandbox, maintains a memory of successful and failed detections, and only promotes high-precision patterns after human review (HITL).',
    backendPort: 8009,
    status: 'Not Started',
    apiPath: 'api/fraud',
    defaultInput: 'Analyze transaction batches for multi-device login activity within 5 minutes followed by small, recurring utility bills.',
    inputLabel: 'Suspicious Behavior Pattern to Test',
    inputPlaceholder: 'Describe fraud hypothesis or parameters...'
  },
  {
    id: 'productivity_agent',
    number: '10',
    title: 'Goal-Driven Personal Productivity Agent',
    category: 'Employee-Facing',
    problem: 'Professionals juggle projects, meetings, and learning goals with no coherent system that plans, prioritizes, and adapts across tools.',
    outcome: 'An agent that understands high-level goals, breaks them into plans, interacts with calendars/email/task systems, reflects on progress in loops, requests clarification or approval when needed, and continuously re-plans as priorities shift.',
    backendPort: 8010,
    status: 'Not Started',
    apiPath: 'api/productivity',
    defaultInput: 'Goal: Publish a technical blog post on Python Agents by Friday, while keeping calendar clear of non-urgent meetings.',
    inputLabel: 'High-Level Goal',
    inputPlaceholder: 'Enter personal or project goals...'
  }
];

const MOCK_TRACES: Record<string, string[]> = {
  backtester: [
    '[INFO] Parsing user prompt: "Buy AAPL when 50-day moving average crosses above 200-day moving average..."',
    '[STEP 1/4] Writing pandas/backtrader backtest python script...',
    '[INFO] Created backtest script in path /tmp/backtester_run.py',
    '[STEP 2/4] Executing python backtest script against historical market database...',
    '[ERROR] Traceback (most recent call last):\n  File "/tmp/backtester_run.py", line 14, in <module>\n    df["MA50"] = df["Close"].rolling(window=50).mean()\nNameError: name \'df\' is not defined',
    '[WARNING] Script execution failed. Activating self-correction agent...',
    '[STEP 3/4] Parsing error trace: Identifier \'df\' was used before loading dataset. Correcting backtest code...',
    '[INFO] Rewrote code block: Loading historical ticker data (AAPL) into DataFrame \'df\'...',
    '[STEP 4/4] Executing corrected backtest script...',
    '[SUCCESS] Python script completed execution with exit code 0.',
    '[INFO] Compiling backtest stats and graphing returns curve...'
  ],
  researcher: [
    '[INFO] Subject query received: "Briefing on Nvidia Q2 growth and AMD chip launches..."',
    '[STEP 1/4] Planner agent breaking task into research objectives: SEC EDGAR filings, analyst releases, and news RSS.',
    '[STEP 2/4] Analyst Agent 1 (EDGAR Searcher) downloading Nvidia Q2 10-Q filing...',
    '[STEP 3/4] Analyst Agent 2 (News Searcher) fetching tech news and benchmark datasets on AMD MI300X chips...',
    '[STEP 4/4] Synthesis Agent identifying potential risks (US export restrictions, supply chain constraints)...',
    '[DEBATE] Agent 1 and Agent 2 comparing Nvidia margin growth assumptions... resolving conflict.',
    '[SUCCESS] Draft briefing generated.'
  ],
  risk_sentinel: [
    '[INFO] Initializing portfolio monitoring sentinel loop...',
    '[STEP 1/3] Fetching real-time regional bank credit spreads and corporate bond yields...',
    '[STEP 2/3] Correlating spreads with credit default swap (CDS) databases...',
    '[WARNING] Volatility spike detected in counterparties matching regional banking profile.',
    '[STEP 3/3] Running Monte Carlo scenario simulations for US High Yield Bond Portfolio...',
    '[WARNING] Value-at-Risk (VaR) threshold of 5% breached under liquidity squeeze scenarios.',
    '[HITL] Flagging account positions and drafting rebalancing recommendation for risk officer review...'
  ],
  reg_change: [
    '[INFO] Reading regulation reference: "SEC Rule 10b-5 amendments"...',
    '[STEP 1/4] Ingesting text and fetching internal company controls directory via semantic RAG...',
    '[STEP 2/4] Identifying impacted compliance areas: Employee pre-clearance rules and daily transaction reporting.',
    '[STEP 3/4] Modeling transaction impact: Regulatory penalty simulation under existing reporting timelines.',
    '[STEP 4/4] Creating proposed controls revisions and drafting operational compliance brief...'
  ],
  incident_coordinator: [
    '[ALERT] Primary Alert: "Database Connection Pool Exhausted" on service: Billing.',
    '[STEP 1/5] Initiating root cause analysis agent workflow...',
    '[STEP 2/5] Inspecting service telemetry: Billing database connections spiked from 20 to 100 in 3 minutes.',
    '[STEP 3/5] Inspecting Git history: Found deploy commit #a8c2f10 "Added billing retry loop" completed 15m ago.',
    '[STEP 4/5] Running mock database trace: Identified unclosed transactions in connection pool retry loop.',
    '[WARNING] Critical issue: Retry loop fails to release DB connection on connection error.',
    '[STEP 5/5] Recommending mitigation: Revert deploy #a8c2f10 or increase connection pool capacity temporarily.'
  ],
  financial_wellness: [
    '[INFO] Loading user financial profile from long-term session memory...',
    '[STEP 1/3] Querying historical savings rates and debt amortization schemas...',
    '[STEP 2/3] Generating debt payoff plan comparison (Snowball vs. Avalanche)...',
    '[STEP 3/3] Drafting personal coaching roadmap and budget suggestions...',
    '[SUCCESS] Budget roadmap updated.'
  ],
  knowledge_synthesis: [
    '[INFO] Scanning files and corporate chat history directories...',
    '[STEP 1/4] Extracting meeting minutes, Slack logs, and updated confluence specs...',
    '[STEP 2/4] Entity mapping: Identifying overlaps in public APIs and core backend contracts...',
    '[WARNING] Timeline Conflict: Team A deprecating API Endpoint v1 on Oct 1; Team B deployment relies on v1 until Dec 15.',
    '[STEP 3/4] Updating Knowledge Graph schema...',
    '[STEP 4/4] Drafting notification brief for product leads to reconcile project timelines...'
  ],
  vendor_negotiator: [
    '[INFO] Initializing contract negotiation workbook...',
    '[STEP 1/3] Parsing Datadog contract terms and comparing against company procurement playbook...',
    '[STEP 2/3] Running RAG search for historical benchmarks: Found similar renewals negotiated at 4.2% rate hike.',
    '[STEP 3/3] Drafting email response: Refusing 8% increase, offering 4.5% backed by volume discount clauses...'
  ],
  fraud_hunter: [
    '[INFO] Scanning sandbox database logs (past 100,000 transactions)...',
    '[STEP 1/4] Querying behavior records for multi-device logins...',
    '[STEP 2/4] Generating fraud threat hypothesis signature...',
    '[STEP 3/4] Running signature test in sandbox: Yielded 98.4% precision and flagged 14 unknown fraudulent sessions.',
    '[STEP 4/4] Storing threat model rule and formatting dashboard card for risk analyst sign-off...'
  ],
  productivity_agent: [
    '[INFO] Ingesting worker goal: "Publish Python portfolio post by Friday"...',
    '[STEP 1/4] Querying Google Calendar and Outlook email queues...',
    '[STEP 2/4] Auto-identifying non-essential events: Rescheduled internal feedback sync...',
    '[STEP 3/4] Blocking 3-hour focused deep-work time blocks in calendar...',
    '[STEP 4/4] Compiling task list and checklist card...'
  ]
};

const MOCK_OUTPUTS: Record<string, string> = {
  backtester: `=== BACKTEST RESULTS ===
Strategy: Simple SMA Crossover (50, 200)
Asset: AAPL (Apple Inc.)
Period: 2021-01-01 to 2026-01-01
Initial Capital: $100,000.00
Final Capital: $223,450.12
Total Return: +123.45%
Annualized Return: 24.69%
Sharpe Ratio: 1.84
Max Drawdown: -12.4%
Trades Executed: 14

=== AUTO-FIXED CODE CODE===
import pandas as pd
import numpy as np

def run_backtest():
    # Load historical market data
    df = pd.read_csv('AAPL_data.csv')
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    ...
    # Strategy successfully verified and run
`,
  researcher: `# RESEARCH BRIEFING: NVIDIA (NVDA) GROWTH & AMD COMPETITION
**Date:** August 12, 2026
**Analysts:** Market Research Team (Multi-Agent)

## Executive Summary
Nvidia Corporation (NVDA) continues to dominate the AI hardware space, reporting record-breaking Q2 revenue. However, mounting regulatory scrutiny on cross-border GPU exports and the commercial deployment of AMD’s MI300X chips introduce key structural risks.

## Key Findings
- **Financial Growth:** NVDA Q2 revenue reached $32.4B (+15% QoQ), driven by Blackwell chip demand.
- **AMD Threat:** AMD MI300X shipments increased 24% this quarter, offering an attractive performance-per-dollar ratio for LLM inference workloads.
- **Export Risks:** Recent updates to EU/US trade compliance schemas require additional licensing steps for sales in Southeast Asia, impacting projected Q4 revenue.

*Sources cited: SEC Filing 10-Q (Aug 2026), tech-logs.com chip benchmarks.*
`,
  risk_sentinel: `=== RISK SENTINEL ALERT ===
[HIGH CONVICTION] Credit Volatility Spike

**Threat Index:** 8.4/10
**Target Portfolio:** US High Yield Bond Portfolio
**Asset Class:** Corporate Debt

**Analysis:** Regional banking credit spreads have widened by 48bps in the past 48 hours. Historical correlations suggest an increased probability of liquidity contractions affecting mid-tier financial bonds.
**Estimated Portfolio VaR Impact:** +$420,000 potential draw under stress.

**Suggested Actions:**
1. Reduce regional bank exposure by 12%.
2. Hedging: Purchase credit default swaps (CDS) index options.
`,
  reg_change: `# REGULATORY COMPLIANCE ASSESSMENT: SEC RULE 10B-5
**Obligation Type:** Transaction Reporting & Insider Trade Safeguards

## Simulated System Impact
- **Systems Affected:** Core Transaction Broker (Equities API), Compliance Auditor DB.
- **Operational Risk:** Delaying daily reporting files under the new rule results in immediate warnings and potential fines.

## Recommended Process Revisions
1. **Control Point 4.1:** Shift transaction log sync from nightly batch jobs to real-time webhook streaming.
2. **Control Point 7.2:** Auto-revoke API key access for designated insiders 15 days before quarterly earnings release.
`,
  incident_coordinator: `# INCIDENT DIAGNOSTIC REPORT: INC-094
**Target Service:** Billing Database Prod
**Status:** Resolved (Mock Action Triggered)

## Timeline & Root Cause
- **12:20 PM:** Billing service database connection count spiked to 100/100.
- **12:25 PM:** Microservices calling 'Billing' returned 500 status.
- **Analysis:** Commit #a8c2f10 introduced a retry loop that failed to release database connections during intermittent network drops, causing a resource leak.

## Mitigation Executed
- Increased database connection limit pool to 150 (temporarily resolved bottleneck).
- Rolled back deployment to commit #a8c2f0f.
`,
  financial_wellness: `# COACHING ROADMAP: JOHN (34)
**Monthly Income:** $7,083 (Pre-tax)
**Savings Target:** $40,000 for home downpayment (in 3 years)

## Recommendation Path
- **Emergency Fund:** Secure $10,000 (approx. 2 months expenses) first.
- **Debt Payoff (Avalanche Strategy):** Allocate an extra $350/month to the $12k Student Loan (4.5% interest rate).
- **Home Savings:** Save $950/month in a High Yield Savings Account (HYSA) returning ~4.5%.

*Action Required: Confirm authorization to link savings accounts for automated weekly tracking.*
`,
  knowledge_synthesis: `# KNOWLEDGE GRAPH TIMELINE SYNC
**Detected Conflict:** API Dev & Integration mismatch.

## Conflict Details
- **Project Alpha API:** Deprecation of API Version 1 scheduled for **October 1**.
- **Project Beta Client:** Scheduled update to API Version 2 set for **December 15**.
- **Impact:** Client onboarding will break for 2.5 months for newly integrated partners.

## Proposed Action
- Postpone API Version 1 deprecation to December 30, OR expedite Project Beta's migration sprint to September 25.
`,
  vendor_negotiator: `# PROCUREMENT DRAFT CORRESPONDENCE
**Target Vendor:** Datadog Inc.
**Proposed Term:** 8% increase in subscription rates

## Redlined Terms
- **Section 4.1 (Fee Indexing):** Amend the maximum annual price increase cap from 8% to a maximum of 4.5% linked to volume commitments.

## Drafted Email Response
"Dear Datadog Team,
We value our partnership and have audited our usage metrics. Based on volume benchmarks, we are willing to commit to a 3-year term with pricing capped at a 4.5% annual rate hike, aligning with our current corporate procurement limits..."
`,
  fraud_hunter: `=== FRAUD DETECTION SIGNATURE SANDBOX ===
**Hypothesis:** Multi-device fast login with micro-transactions.

**Evaluation Run Summary:**
- **Datasets Analyzed:** 100,000 test logs.
- **True Positives (Fraud Captured):** 14 accounts.
- **False Positives (Clean Flagged):** 1 account.
- **Precision Metric:** 93.3%
- **Recall Metric:** 87.5%

**Signature Pattern Rule:**
\`\`\`sql
SELECT user_id, count(device_id) FROM logins
WHERE login_time > NOW() - INTERVAL '5 minutes'
GROUP BY user_id HAVING count(device_id) >= 3;
\`\`\`
`,
  productivity_agent: `# PERSONAL SPRINT SCHEDULE
**Primary Goal:** Publish Python agent portfolio post by Friday.

## Scheduled Deep-Work Blocks
- **Wednesday:** 9:00 AM - 12:00 PM (Drafting code examples)
- **Thursday:** 1:00 PM - 4:00 PM (Writing explanations)
- **Friday:** 10:00 AM - 1:00 PM (Final editing & deployment)

## Automated Calendar Actions
- **Rescheduled:** "Team Coffee Chat" shifted to Monday, Aug 17.
- **Auto-drafted email:** Send response to Mark apologizing for postponing the non-urgent sync.
`
};

export default function App() {
  const [selectedProject, setSelectedProject] = useState<Project>(PROJECTS[0]);
  const [inputVal, setInputVal] = useState<string>(PROJECTS[0].defaultInput);
  const [isLiveMode, setIsLiveMode] = useState<boolean>(false);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [terminalLines, setTerminalLines] = useState<string[]>([]);
  const [outputResult, setOutputResult] = useState<string>('');
  
  const terminalEndRef = useRef<HTMLDivElement>(null);

  // Sync inputs when selecting different projects
  useEffect(() => {
    setInputVal(selectedProject.defaultInput);
    setTerminalLines([]);
    setOutputResult('');
  }, [selectedProject]);

  // Scroll to bottom of terminal
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [terminalLines]);

  const handleRunDemo = async () => {
    setIsRunning(true);
    setTerminalLines([]);
    setOutputResult('');

    if (isLiveMode) {
      // Direct API Request to the specific Python backend port
      const backendUrl = `http://localhost:${selectedProject.backendPort}/${selectedProject.apiPath}`;
      try {
        setTerminalLines([`[INFO] Direct API mode active: Connecting to ${backendUrl}...`]);
        const response = await fetch(backendUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ input: inputVal })
        });
        
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        setTerminalLines(prev => [...prev, `[SUCCESS] Received clean response from Python API.`]);
        setOutputResult(typeof data === 'string' ? data : JSON.stringify(data, null, 2));
      } catch (err: any) {
        setTerminalLines(prev => [
          ...prev,
          `[ERROR] Connection failed: ${err.message}`,
          `[INFO] Please ensure the Python backend server for this project is running on port ${selectedProject.backendPort}.`
        ]);
        setOutputResult('');
      } finally {
        setIsRunning(false);
      }
    } else {
      // Mock simulation mode
      const traceLines = MOCK_TRACES[selectedProject.id] || [];
      const outputText = MOCK_OUTPUTS[selectedProject.id] || '';

      // Stream lines into terminal for a realistic feel
      let lineIndex = 0;
      const interval = setInterval(() => {
        if (lineIndex < traceLines.length) {
          setTerminalLines(prev => [...prev, traceLines[lineIndex]]);
          lineIndex++;
        } else {
          clearInterval(interval);
          setOutputResult(outputText);
          setIsRunning(false);
        }
      }, 500);
    }
  };

  const getLineClass = (line: string) => {
    if (line.includes('[ERROR]')) return 'line-error';
    if (line.includes('[WARNING]')) return 'line-warning';
    if (line.includes('[SUCCESS]')) return 'line-success';
    if (line.includes('[STEP')) return 'line-step';
    return 'line-info';
  };

  return (
    <div className="app-container">
      {/* Sidebar navigation */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>Agentic AI Systems</h1>
          <p>Portfolio of Python Demos</p>
        </div>
        <nav className="sidebar-menu">
          {PROJECTS.map((project) => (
            <button
              key={project.id}
              onClick={() => setSelectedProject(project)}
              className={`menu-item ${selectedProject.id === project.id ? 'active' : ''}`}
            >
              <span className="item-number">{project.number}</span>
              <div className="item-details">
                <span className="item-title">{project.title}</span>
                <span className="item-category">{project.category}</span>
              </div>
              <span className={`status-dot not-started`} title="Not Started" />
            </button>
          ))}
        </nav>
      </aside>

      {/* Main content display */}
      <main className="main-content">
        <header className="project-header">
          <div className="project-title-area">
            <h2>{selectedProject.title}</h2>
            <div className="project-meta">
              <span className="category-tag">{selectedProject.category}</span>
              <span className="separator">|</span>
              <span className="port-tag">Backend Port: {selectedProject.backendPort}</span>
            </div>
          </div>
          <div className={`status-badge not-started`}>
            Not Started
          </div>
        </header>

        <section className="project-body">
          {/* Problem and Desired Outcome Cards */}
          <div className="info-cards">
            <div className="card">
              <h3>The Problem</h3>
              <p>{selectedProject.problem}</p>
            </div>
            <div className="card">
              <h3>Desired Outcome</h3>
              <p>{selectedProject.outcome}</p>
            </div>
          </div>

          {/* Interactive Playground Control Card */}
          <div className="playground-section">
            <h3 className="section-title">Interactive Playground</h3>
            
            <div className="controls-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <h4>Demo Run Config</h4>
                <div className="mode-toggle">
                  <button 
                    className={`mode-btn ${!isLiveMode ? 'active' : ''}`}
                    onClick={() => setIsLiveMode(false)}
                  >
                    Simulated Mode
                  </button>
                  <button 
                    className={`mode-btn ${isLiveMode ? 'active' : ''}`}
                    onClick={() => setIsLiveMode(true)}
                  >
                    Live Python Backend
                  </button>
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="user-input">{selectedProject.inputLabel}</label>
                <textarea
                  id="user-input"
                  rows={3}
                  value={inputVal}
                  onChange={(e) => setInputVal(e.target.value)}
                  placeholder={selectedProject.inputPlaceholder}
                  disabled={isRunning}
                />
              </div>

              <div className="button-row">
                <button
                  className="btn btn-primary"
                  onClick={handleRunDemo}
                  disabled={isRunning || !inputVal.trim()}
                >
                  {isRunning ? 'Running Agent...' : 'Execute Agent System'}
                </button>
              </div>
            </div>

            {/* Terminal Feed Display */}
            <div className="terminal-card">
              <div className="terminal-header">
                <div className="terminal-dots">
                  <span className="dot red" />
                  <span className="dot yellow" />
                  <span className="dot green" />
                </div>
                <span className="terminal-title">agent_trace_output.log</span>
                <span />
              </div>
              <div className="terminal-body">
                {terminalLines.length === 0 && (
                  <span style={{ color: 'var(--text-secondary)' }}>
                    Terminal ready. Click "Execute Agent System" to run the workflow.
                  </span>
                )}
                {terminalLines.map((line, idx) => (
                  <div key={idx} className={`terminal-line ${getLineClass(line)}`}>
                    {line}
                  </div>
                ))}
                {isRunning && (
                  <div className="terminal-line line-info" style={{ animation: 'pulse 1.5s infinite' }}>
                    ▊ Running next agentic cycle...
                  </div>
                )}
                <div ref={terminalEndRef} />
              </div>
            </div>

            {/* Agent Results Display */}
            {outputResult && (
              <div className="output-panel">
                <h4 className="output-title">Synthesized Agent Outputs</h4>
                <pre className="output-content">{outputResult}</pre>
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
