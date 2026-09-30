"""One real Jev call for the pinned checkout incident candidate."""

import asyncio

import logfire

from backend.incident_investigation.classifier import classify_candidate, decide
from backend.incident_investigation.smoketests._common import (
    emit,
    load_candidate,
    require_key,
)


async def check() -> None:
    summary = load_candidate("checkout_candidate.json")
    with logfire.span("Checkout Jev single-request smoke") as span:
        context = span.get_span_context()
        trace_id = f"{context.trace_id:032x}" if context and context.is_valid else None
        judgment = await classify_candidate(summary)
    outcome = decide(summary, judgment).outcome
    emit(
        {
            "input": "checkout_candidate.json",
            "expected": "incident",
            "outcome": outcome,
            "probability": judgment.probability,
            "usage": judgment.usage,
            "trace_id": trace_id,
        }
    )
    if outcome != "incident":
        raise AssertionError(f"expected incident, got {outcome}")


if __name__ == "__main__":
    require_key("TYPESAFE_API_KEY")
    asyncio.run(check())
