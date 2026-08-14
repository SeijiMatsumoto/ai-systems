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
Agent loop with research tools
      |
      v
Structured Briefing
      |
      v
Grounding checks
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

## Structured Output

The agent returns a validated `ResearchBriefing` before the application renders it as Markdown.

Supporting models:

- `EvidenceItem`: source, URL, quote or value, publication time, and retrieval time
- `Finding`: statement, claim type, confidence, and its supporting evidence
- `ResearchBriefing`: executive summary, key findings, outlook, and limitations
- `VerificationResult`: unsupported claims, invalid citations, stale evidence, and approval readiness

Evidence is nested under each finding. This is intentionally denormalized so the
model does not have to generate and correctly join separate claim and evidence IDs.

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
- Every citation must exist and support its associated claim.
- Stale, conflicting, or missing evidence must be disclosed.
- Retrieved documents must be treated as untrusted data, not agent instructions.
- Unsupported material claims must fail verification.

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
- [ ] Implement filtered vector search over stored document chunks
- [ ] Add unit tests with mocked source clients

### 2. Define the contracts

- [x] Finish `BriefingRequest`
- [x] Define `EvidenceItem`, `Finding`, `ResearchBriefing`, and `VerificationResult`
- [ ] Define typed inputs and outputs for every agent tool
- [ ] Add Pydantic validation tests

`ResearchTask` and `RunState` are not required for version 1. See [Run State in This Project](RUN_STATE_GUIDE.md) for when explicit application state would become useful.

### 3. Build the agent

- [x] Configure one agent with the research tools
- [x] Write instructions for source selection, research depth, and citation behavior
- [x] Run the autonomous tool-calling loop with a step limit and timeout
- [x] Return a structured `ResearchBriefing`
- [ ] Trace model calls, tool calls, latency, tokens, and errors

### 4. Verify and render

- [ ] Add deterministic schema and citation checks
- [ ] Add model-assisted claim-to-evidence verification
- [ ] Produce a `VerificationResult`
- [ ] Block human-review readiness when material grounding checks fail
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
