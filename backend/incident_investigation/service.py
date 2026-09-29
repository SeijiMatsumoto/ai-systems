"""Run the incident investigator with a durable shared run ID and stop state."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from typing import Any, Literal

import logfire
from pydantic_ai import UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models import Model
from sqlalchemy.orm import Session

from backend.db import db_utils
from backend.db.llm_runs import complete_run, create_run, fail_run, start_run
from backend.incident_investigation.agent import (
    MAX_TOOL_CALLS,
    InvestigationDraft,
    InvestigatorDeps,
    ToolStep,
    agent,
)
from backend.incident_investigation.contracts import (
    IncidentReport,
    InvestigationRequest,
    VerificationResult,
)
from backend.incident_investigation.telemetry import TelemetryStore
from backend.incident_investigation.verification import verify_report
from backend.observability import EXPORT_ENABLED

SessionScope = Callable[[], AbstractContextManager[Session]]
RUN_TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class InvestigationExecution:
    run_id: uuid.UUID
    status: Literal["completed", "failed"]
    stop_reason: Literal[
        "completed", "timeout", "budget_exhausted", "agent_error", "verification_failed"
    ]
    draft: InvestigationDraft | None
    report: IncidentReport | None
    verification: VerificationResult | None
    tool_steps: list[ToolStep]
    surfaced_evidence_ids: list[str]
    logfire_trace_id: str | None
    usage: dict[str, Any]
    error_type: str | None = None


def _prompt(store: TelemetryStore, deps: InvestigatorDeps) -> str:
    available_metrics = {
        service: sorted(
            {point.metric for point in store.metrics if point.service == service}
        )
        for service in sorted(deps.scope.allowed_services)
    }
    context = {
        "alert": store.manifest.alert.model_dump(mode="json"),
        "window_start": deps.scope.start.isoformat(),
        "window_end": deps.scope.end.isoformat(),
        "allowed_services": sorted(deps.scope.allowed_services),
        "available_metrics": available_metrics,
        "declared_coverage_gaps": [
            gap.model_dump(mode="json")
            for gap in store.manifest.coverage_gaps
            if gap.service in deps.scope.allowed_services
        ],
        "tool_call_budget": MAX_TOOL_CALLS,
    }
    return json.dumps(context, sort_keys=True)


async def run_investigation(
    request: InvestigationRequest,
    *,
    store: TelemetryStore | None = None,
    session_scope: SessionScope = db_utils.get_session,
    model: Model | str | None = None,
    timeout_seconds: float = RUN_TIMEOUT_SECONDS,
) -> InvestigationExecution:
    """Execute one draft and verify its citations before accepting a report."""
    store = store or TelemetryStore()
    if request.service != store.manifest.alert.service:
        raise ValueError("request service does not match alert service")
    scope = store.scope_for_alert(
        request.alert_id, request.window_start, request.window_end
    )
    deps = InvestigatorDeps(store=store, scope=scope)

    with session_scope() as session:
        run_id = create_run(session, "incident_investigation").id

    with logfire.span(
        "Incident investigation {run_id}",
        run_id=str(run_id),
        alert_id=request.alert_id,
    ) as span:
        context = span.get_span_context()
        trace_id = (
            f"{context.trace_id:032x}"
            if EXPORT_ENABLED and context is not None and context.is_valid
            else None
        )
        usage: dict[str, Any] = {}
        with session_scope() as session:
            start_run(session, run_id, logfire_trace_id=trace_id)
        try:
            async with asyncio.timeout(timeout_seconds):
                result = await agent.run(
                    _prompt(store, deps),
                    deps=deps,
                    model=model,
                    run_id=str(run_id),
                    usage_limits=UsageLimits(
                        request_limit=10,
                        tool_calls_limit=MAX_TOOL_CALLS + 1,
                        total_tokens_limit=25_000,
                        output_tokens_limit=4_000,
                    ),
                    metadata={
                        "run_id": str(run_id),
                        "system_key": "incident_investigation",
                    },
                )
            usage = asdict(result.usage)
            if any(step.error == "tool call budget exhausted" for step in deps.steps):
                raise UsageLimitExceeded("incident tool call budget exhausted")
        except (TimeoutError, UsageLimitExceeded) as exc:
            stop_reason: Literal["timeout", "budget_exhausted", "agent_error"] = (
                "timeout" if isinstance(exc, TimeoutError) else "budget_exhausted"
            )
            error_type = type(exc).__name__
        except asyncio.CancelledError:
            with session_scope() as session:
                fail_run(session, run_id, logfire_trace_id=trace_id)
            raise
        except Exception as exc:  # noqa: BLE001 - provider and tool failures are reported as failed runs
            stop_reason = "agent_error"
            error_type = type(exc).__name__
        else:
            try:
                report, verification = verify_report(
                    result.output,
                    store=store,
                    scope=scope,
                    surfaced_evidence_ids=deps.surfaced_evidence_ids,
                )
            except Exception:
                with session_scope() as session:
                    fail_run(session, run_id, logfire_trace_id=trace_id)
                raise
            with session_scope() as session:
                if verification.passed:
                    complete_run(session, run_id)
                else:
                    fail_run(session, run_id, logfire_trace_id=trace_id)
            return InvestigationExecution(
                run_id=run_id,
                status="completed" if verification.passed else "failed",
                stop_reason="completed"
                if verification.passed
                else "verification_failed",
                draft=result.output,
                report=report,
                verification=verification,
                tool_steps=list(deps.steps),
                surfaced_evidence_ids=sorted(deps.surfaced_evidence_ids),
                logfire_trace_id=trace_id,
                usage=usage,
            )

        with session_scope() as session:
            fail_run(session, run_id, logfire_trace_id=trace_id)
        return InvestigationExecution(
            run_id=run_id,
            status="failed",
            stop_reason=stop_reason,
            draft=None,
            report=None,
            verification=None,
            tool_steps=list(deps.steps),
            surfaced_evidence_ids=sorted(deps.surfaced_evidence_ids),
            logfire_trace_id=trace_id,
            usage=usage,
            error_type=error_type,
        )
