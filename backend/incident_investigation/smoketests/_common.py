"""Fixture loading and one-request execution shared by named smoke scripts."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import logfire
from pydantic_ai import CallToolsNode, UsageLimits
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model

from backend.incident_investigation.agent import InvestigatorDeps, agent
from backend.incident_investigation.classifier import CandidateSummary
from backend.incident_investigation.contracts import DetectedIncident
from backend.incident_investigation.detection import REPLAY_FIXTURE_DIR
from backend.incident_investigation.service import _prompt
from backend.incident_investigation.telemetry import TelemetryStore

FIXTURES = Path(__file__).parent / "fixtures"


def require_key(name: str) -> None:
    if not os.getenv(name):
        raise SystemExit(f"{name} is required in backend/.env")


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, default=str))


def load_candidate(name: str) -> CandidateSummary:
    return CandidateSummary.model_validate_json((FIXTURES / name).read_text())


def checkout_context() -> tuple[str, InvestigatorDeps, TelemetryStore]:
    detected = DetectedIncident.model_validate_json(
        (FIXTURES / "checkout_trigger.json").read_text()
    )
    store = TelemetryStore(REPLAY_FIXTURE_DIR).snapshot(detected.observed_at)
    scope = store.scope_for_detection(
        detected.incident_id,
        detected.service,
        detected.window_start,
        detected.window_end,
    )
    deps = InvestigatorDeps(store=store, scope=scope)
    return _prompt(store, deps, detected), deps, store


async def one_investigator_response(
    prompt: str,
    deps: InvestigatorDeps,
    *,
    message_history: list[ModelMessage] | None = None,
    model: Model | str | None = None,
) -> tuple[ModelResponse, dict[str, Any], str | None]:
    """Stop at the first model response, before any tool or follow-up request."""
    with logfire.span("Incident investigator one-request smoke") as span:
        context = span.get_span_context()
        trace_id = f"{context.trace_id:032x}" if context and context.is_valid else None
        async with agent.iter(
            prompt,
            deps=deps,
            message_history=message_history,
            model=model,
            usage_limits=UsageLimits(request_limit=1),
        ) as run:
            async for node in run:
                if isinstance(node, CallToolsNode):
                    usage = asdict(run.usage)
                    if usage["requests"] != 1 or deps.steps:
                        raise AssertionError(
                            "smoke executed more than one model request or a tool"
                        )
                    return node.model_response, usage, trace_id
    raise AssertionError("model did not return a response")
