# Multi-Agent Research & Briefing System (External / Client-Facing)

## The Problem
Analysts and clients spend hours piecing together fragmented market, company, and regulatory information from filings, news, and internal notes.

## Desired Outcome
An agent team that autonomously plans research, retrieves and synthesizes information (RAG over proprietary + public sources), debates findings, and produces a polished, cited briefing that a human can approve or refine before delivery.

---

## Setup & Execution

### Ingestion
First, we need to set up an ingestion flow, where we read from a variety of sources. We will use free APIs to ingest context. Anything with free form text, such as filings or news should be embedded for future RAG use. Anything that changes more often should be cached with Redis with TTL. 

Inputs:
- Company Ticker

Output:
- Structured report of the company. The current state of the company and what to expect.

Data sources:
- [x] MARKET DATA: Yahoo finance API (https://github.com/ranaroussi/yfinance), Massive (https://massive.com/dashboard)
    - Close prices from 3mo ago to now
- [x] FILINGS: Edgar
- [x] COMPANY PROFILE: Yahoo finance API
- [x] NEWS: Marketaux or GNews API