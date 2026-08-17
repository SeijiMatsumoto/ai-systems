# Agentic Research & Briefing System

## Goal

Build a client-facing agent that researches a public company using market-data, filing, and news tools, then returns a grounded briefing for human review.

This project primarily practices writing Python for agentic systems: defining tools, running an autonomous tool-calling loop, producing structured output, enforcing limits, validating citations, and evaluating behavior.

## Architecture

Version 1 uses one autonomous agent. The agent receives the available tools and continues choosing and calling them until it produces a final answer or reaches a configured step limit or timeout.

```text
BriefingRequest
      |
      v
Validate request and check cache
      |
      v
Agent loop with compact evidence candidates
      |
      v
Draft claims with evidence IDs
      |
      v
Deterministic validation and semantic grounding
      |
      v
One bounded repair attempt; exclude anything still unsupported
      |
      v
Rebuild and verify the narrative from grounded findings
      |
      v
Markdown and human review
```

There is no separate planning call, explicit task queue, or application-managed research state in version 1. The agent's message and tool-call context tracks its research trajectory.

A multi-agent design is a possible future experiment, but it should only be added if evaluations show that parallel workers materially improve coverage or latency.

## Request

`BriefingRequest` contains:

- `symbol`
- `as_of`
- `research_question`
- `audience`
- `time_horizon`

Comparison companies and other advanced research options are out of scope for version 1.

## Tools

The agent should receive small, typed Python tools:

- Search stored filings by query
- Search stored news by query and date range
- Fetch the company profile
- Fetch market data
- Retrieve the source content needed to verify a citation

Tool responses should have consistent types and include source provenance. Tools should raise explicit errors rather than print failures or silently return `None`.

The model sees compact candidate views rather than complete provenance records. The
request-scoped dependencies keep the authoritative evidence catalog and raw financial
sources, protected by a lock because independent tools may execute in parallel. A
document search returns at most three passages to the model. Internally it retrieves a
larger seed pool, expands adjacent chunks, removes boilerplate, and globally ranks
passages so the token bound does not reduce retrieval quality. Historical financials
return a curated set of metrics unless the agent requests up to 12 exact metric names.
Daily prices are reduced to start, end, low, and high points before they enter the
model context.

## Structured Output

The agent returns a `DraftResearchBriefing`. It writes claims and selects stable
`evidence_id` values from tool results; it does not reproduce quotes, values, URLs,
or source metadata. Python resolves those IDs from an evidence catalog, validates the
source locators, and constructs the final `ResearchBriefing`.

Supporting models:

- `DraftFinding`: statement, claim type, confidence, and selected evidence IDs
- `DocumentEvidence`: an exact passage and offsets in a stored document chunk
- `FinancialEvidence`: an exact scalar value and path in structured financial data
- `Finding`: a draft finding hydrated with authoritative evidence records
- `ResearchBriefing`: executive summary, key findings, outlook, and limitations
- `VerificationResult`: unsupported claims, invalid citations, stale evidence, and approval readiness

Final evidence is nested under each finding for simple API and UI consumption. During
generation it is normalized into a run-scoped evidence catalog, so the model only
selects IDs and Python owns the source contents.

Filings and news are not separate evidence models. Both are rows in `Document`, so
both use `DocumentEvidence`; `document_type` distinguishes `filing`, `article`, and
`generic`, while `content_quality` distinguishes full text from a snippet. Structured
financial data uses `FinancialEvidence` because its locator is a `field_path` and its
authoritative payload is a scalar value rather than document text.

Facts, calculations, inferences, and forward-looking statements should be distinguishable.

## Limits and Grounding

Python and the agent runtime enforce:

- Maximum agent steps
- Overall timeout
- Bounded tool retries
- Provider rate limits
- Structured-output validation

Before human review:

- Every externally verifiable claim must reference evidence.
- Every selected evidence ID must exist in the run-scoped catalog.
- Document passages must match the stored chunk hash and exact character offsets.
- Financial values must match the value at the stored source object's field path.
- Stale, conflicting, or missing evidence must be disclosed.
- Retrieved documents must be treated as untrusted data, not agent instructions.
- Rejected findings receive one evidence-bounded repair attempt and a second grounding
  check.
- Findings that still fail are excluded from the user-facing briefing.
- The executive summary and outlook are rebuilt from verified findings, checked again,
  and replaced with deterministic grounded fallbacks if synthesis fails.

## Caching

Do not reuse a briefing based only on whether it was created in the last 24 hours. Create a fingerprint from the normalized request and relevant workflow versions.

Version 1 fingerprint inputs:

- `BriefingRequest`
- Prompt version
- Model version
- Tool version

Store the source timestamps and identifiers with the cached briefing so its freshness remains inspectable. More advanced source-snapshot invalidation can be added later.

## Data Sources

- [x] Market history through Yahoo Finance
- [x] Company profile through Yahoo Finance
- [x] SEC filing ingestion through EDGAR
- [x] News ingestion through GNews
- [ ] Decide later whether Massive adds useful coverage

Free-form filings and articles are chunked and embedded for retrieval. Frequently changing structured data is cached with a source-appropriate TTL.

## Implementation Checklist

### 1. Stabilize the data layer

- [ ] Remove external calls that run during module import
- [ ] Normalize return types and validate upstream responses
- [ ] Add HTTP timeouts, status checks, rate-limit handling, and typed errors
- [ ] Preserve source, publication, retrieval, and freshness metadata
- [x] Implement filtered vector search over stored document chunks
- [x] Add bounded adjacent-chunk expansion and passage-quality filtering
- [x] Add unit tests with mocked source clients

### 2. Define the contracts

- [x] Finish `BriefingRequest`
- [x] Define draft, document, financial, final briefing, and verification contracts
- [x] Define typed inputs and outputs for every agent tool
- [x] Add focused evidence-contract and hydration tests

`ResearchTask` and `RunState` are not required for version 1. See [Run State in This Project](RUN_STATE_GUIDE.md) for when explicit application state would become useful.

### 3. Build the agent

- [x] Configure one agent with the research tools
- [x] Write instructions for source selection, research depth, and citation behavior
- [x] Run the autonomous tool-calling loop with a step limit and timeout
- [x] Return a structured `ResearchBriefing`
- [x] Trace model calls, tool calls, latency, tokens, and errors

### 4. Verify and render

- [x] Add deterministic schema and evidence-locator checks
- [x] Add model-assisted claim-to-evidence verification
- [x] Repair rejected findings once and exclude anything still unsupported
- [x] Rebuild and verify summary and outlook from grounded findings
- [x] Produce a `VerificationResult`
- [x] Block human-review readiness when material grounding checks fail
- [ ] Render the validated briefing as Markdown

### 5. Cache

- [ ] Normalize and fingerprint each request
- [ ] Include prompt, model, and tool versions in the fingerprint
- [ ] Save source metadata with each cached briefing
- [ ] Add cache-hit and cache-invalidation tests

### 6. Evaluate

- [ ] Create 15–20 representative requests
- [ ] Include sparse, stale, contradictory, irrelevant, and malicious retrieved content
- [ ] Measure citation correctness, claim support, completeness, usefulness, latency, and cost
- [ ] Save failures as regression cases
- [ ] Use results to decide whether multi-agent research is worth testing

### 7. Expose the system

- [ ] Add a FastAPI endpoint that accepts a request and returns a briefing
- [ ] Add a simple UI to submit requests and render Markdown
- [ ] Show citations and verification failures in the UI
- [ ] Add human approve, revise, and reject actions

## Future Iterations

- Comparison-company research
- Durable run recovery
- Asynchronous progress updates
- Mid-run human approval
- Multi-agent parallel research
- Proprietary or synthetic internal notes
