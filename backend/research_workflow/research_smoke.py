"""Run the research workflow directly without starting FastAPI.

Example:
    uv run python -m backend.research_workflow.research_smoke
"""

import argparse
import asyncio
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

import logfire

from backend.research_workflow.contracts import BriefingRequest
from backend.research_workflow.service.research import (
    run_research_workflow,
)

DEFAULT_LOGFIRE_PROJECT_URL = "https://logfire-us.pydantic.dev/seijim27/ai-systems"


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime, treating a missing timezone as UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the research workflow")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument(
        "--question",
        default=(
            "What are Apple's primary business risks, and which are most "
            "consequential for investors over the next 12 months?"
        ),
    )
    parser.add_argument("--audience", default="investors")
    parser.add_argument("--time-horizon", default="12m")
    parser.add_argument(
        "--as-of",
        type=parse_datetime,
        help="ISO-8601 datetime; defaults to the current UTC time",
    )
    parser.add_argument(
        "--logfire-project-url",
        default=os.getenv("LOGFIRE_PROJECT_URL", DEFAULT_LOGFIRE_PROJECT_URL),
        help="Logfire project URL used to construct the printed trace link",
    )
    return parser.parse_args()


def build_trace_url(project_url: str, trace_id: str) -> str:
    query = urlencode({"q": f"trace_id='{trace_id}'", "last": "1h"})
    return f"{project_url.rstrip('/')}/?{query}"


async def main() -> None:
    args = parse_args()
    request = BriefingRequest(
        symbol=args.symbol.strip().upper(),
        as_of=args.as_of or datetime.now(timezone.utc),
        research_question=args.question,
        audience=args.audience,
        time_horizon=args.time_horizon,
    )

    trace_id: str | None = None
    result = None
    try:
        with logfire.span(
            "Research workflow smoke test for {symbol}",
            symbol=request.symbol,
            as_of=request.as_of.isoformat(),
        ) as span:
            span_context = span.get_span_context()
            if span_context is not None and span_context.is_valid:
                trace_id = f"{span_context.trace_id:032x}"
            result = await run_research_workflow(request)
    finally:
        logfire.force_flush()
        if trace_id is not None:
            print(
                "\nLogfire trace:\n"
                f"{build_trace_url(args.logfire_project_url, trace_id)}"
            )

    if result is None:
        raise RuntimeError("Research workflow did not return a result")

    print("\nWorkflow result:")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
