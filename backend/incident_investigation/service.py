"""Run the incident investigator with a durable shared run ID and stop state."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

import logfire
from pydantic_ai import UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage
from sqlalchemy.orm import Session

from backend.db import db_utils
from backend.db.llm_runs import complete_run, create_run, fail_run, start_run
from backend.incident_investigation.agent import (
    INVESTIGATOR_INSTRUCTIONS,
    INVESTIGATOR_MODEL,
    MAX_TOOL_CALLS,
    InvestigationDraft,
    InvestigatorDeps,
    ToolStep,
    agent,
)
from backend.incident_investigation.contracts import (
    DetectedIncident,
    IncidentReport,
    InvestigationRequest,
    VerificationResult,
    WorkflowStep,
)
from backend.incident_investigation.telemetry import TelemetryStore
from backend.incident_investigation.verification import verify_report
from backend.observability import EXPORT_ENABLED

SessionScope = Callable[[], AbstractContextManager[Session]]
RUN_TIMEOUT_SECONDS = 90
TOTAL_TOKENS_LIMIT = 50_000
INVESTIGATION_GATE = asyncio.Semaphore(1)


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
    workflow_steps: list[WorkflowStep] = field(default_factory=list)
    error_type: str | None = None


def _prompt(
    store: TelemetryStore, deps: InvestigatorDeps, detected: DetectedIncident | None
) -> str:
    available_metrics = {
        service: sorted(
            {point.metric for point in store.metrics if point.service == service}
        )
        for service in sorted(deps.scope.allowed_services)
    }
    context = {
        "trigger": detected.model_dump(mode="json")
        if detected is not None
        else store.manifest.alert.model_dump(mode="json"),
        "window_start": deps.scope.start.isoformat(),
        "window_end": deps.scope.end.isoformat(),
        "allowed_services": sorted(deps.scope.allowed_services),
        "available_metrics": available_metrics,
        "declared_coverage_gaps": [
            gap.model_dump(mode="json")
            for gap in store.manifest.coverage_gaps
            if gap.service in deps.scope.allowed_services
            and gap.start < deps.scope.end
            and gap.end > deps.scope.start
        ],
        "tool_call_budget": MAX_TOOL_CALLS,
    }
    return json.dumps(context, sort_keys=True)


async def _run_investigation(
    request: InvestigationRequest | None,
    *,
    store: TelemetryStore | None = None,
    session_scope: SessionScope = db_utils.get_session,
    model: Model | str | None = None,
    timeout_seconds: float = RUN_TIMEOUT_SECONDS,
    on_step: Callable[[WorkflowStep], None] | None = None,
    detected: DetectedIncident | None = None,
    existing_run_id: uuid.UUID | None = None,
) -> InvestigationExecution:
    """Execute one draft and verify its citations before accepting a report."""
    store = store or TelemetryStore()
    if (request is None) == (detected is None):
        raise ValueError("provide one investigation trigger")
    if detected is not None:
        scope = store.scope_for_detection(
            detected.incident_id,
            detected.service,
            detected.window_start,
            detected.window_end,
        )
        trigger_id = detected.incident_id
        service = detected.service
    else:
        if (
            store.manifest.alert is None
            or request.service != store.manifest.alert.service
        ):
            raise ValueError("request service does not match alert service")
        scope = store.scope_for_alert(
            request.alert_id, request.window_start, request.window_end
        )
        trigger_id = request.alert_id
        service = request.service
    started_at = time.perf_counter()
    workflow_steps: list[WorkflowStep] = []

    def emit(
        stage: Literal["scope", "registry", "agent", "tool", "verification"],
        status: Literal["completed", "failed", "running"],
        summary: str,
        details: dict[str, Any],
    ) -> None:
        step = WorkflowStep(
            sequence=len(workflow_steps) + 1,
            stage=stage,
            status=status,
            summary=summary,
            details=details,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        )
        workflow_steps.append(step)
        if on_step is not None:
            on_step(step)

    def record_tool(step: ToolStep) -> None:
        emit(
            "tool",
            "failed" if step.error else "completed",
            f"{step.tool_name.replace('_', ' ')} returned {len(step.returned_evidence_ids)} evidence records",
            step.model_dump(mode="json"),
        )

    def record_tool_choice(name: str, arguments: dict[str, Any]) -> None:
        emit(
            "agent",
            "running",
            f"Investigator selected {name.replace('_', ' ')}",
            {"tool_name": name, "arguments": arguments},
        )

    deps = InvestigatorDeps(
        store=store,
        scope=scope,
        on_tool_start=record_tool_choice,
        on_step=record_tool,
    )
    emit(
        "scope",
        "completed",
        "Trigger and investigation scope validated",
        {
            "trigger_id": trigger_id,
            "service": service,
            "window_start": scope.start.isoformat(),
            "window_end": scope.end.isoformat(),
            "allowed_services": sorted(scope.allowed_services),
        },
    )

    if existing_run_id is None:
        with session_scope() as session:
            run_id = create_run(session, "incident_investigation").id
        emit("registry", "completed", "Run ID created", {"run_id": str(run_id)})
    else:
        run_id = existing_run_id
        emit(
            "registry", "completed", "Simulation run ID reused", {"run_id": str(run_id)}
        )

    with logfire.span(
        "Incident investigation {run_id}",
        run_id=str(run_id),
        trigger_id=trigger_id,
    ) as span:
        context = span.get_span_context()
        trace_id = (
            f"{context.trace_id:032x}"
            if EXPORT_ENABLED and context is not None and context.is_valid
            else None
        )
        usage: dict[str, Any] = {}
        run_usage = RunUsage()
        failure_detail: str | None = None
        if existing_run_id is None:
            with session_scope() as session:
                start_run(session, run_id, logfire_trace_id=trace_id)
            emit(
                "registry",
                "running",
                "Run marked running",
                {"logfire_trace_id": trace_id},
            )
        prompt = _prompt(store, deps, detected)
        emit(
            "agent",
            "running",
            "Investigator started with scoped context and limits",
            {
                "context": json.loads(prompt),
                "instructions": INVESTIGATOR_INSTRUCTIONS.strip(),
                "model": model
                if isinstance(model, str)
                else type(model).__name__
                if model
                else INVESTIGATOR_MODEL,
                "tool_call_budget": MAX_TOOL_CALLS,
                "parallel_tool_calls": False,
                "model_request_limit": 10,
                "total_tokens_limit": TOTAL_TOKENS_LIMIT,
                "output_tokens_limit": 4_000,
                "timeout_seconds": timeout_seconds,
            },
        )
        try:
            async with asyncio.timeout(timeout_seconds):
                result = await agent.run(
                    prompt,
                    deps=deps,
                    model=model,
                    run_id=str(run_id),
                    usage_limits=UsageLimits(
                        request_limit=10,
                        tool_calls_limit=MAX_TOOL_CALLS + 1,
                        total_tokens_limit=TOTAL_TOKENS_LIMIT,
                        output_tokens_limit=4_000,
                    ),
                    usage=run_usage,
                    metadata={
                        "run_id": str(run_id),
                        "system_key": "incident_investigation",
                    },
                )
            usage = asdict(result.usage)
            if any(step.error == "tool call budget exhausted" for step in deps.steps):
                raise UsageLimitExceeded("incident tool call budget exhausted")
            emit(
                "agent",
                "completed",
                "Investigator returned a draft",
                {"draft": result.output.model_dump(mode="json"), "usage": usage},
            )
        except (TimeoutError, UsageLimitExceeded) as exc:
            stop_reason: Literal["timeout", "budget_exhausted", "agent_error"] = (
                "timeout" if isinstance(exc, TimeoutError) else "budget_exhausted"
            )
            error_type = type(exc).__name__
            failure_detail = (
                str(exc)
                if isinstance(exc, UsageLimitExceeded)
                else f"Investigation exceeded {timeout_seconds:g} seconds"
            )
            usage = asdict(run_usage)
        except asyncio.CancelledError:
            if existing_run_id is None:
                with session_scope() as session:
                    fail_run(session, run_id, logfire_trace_id=trace_id)
            raise
        except Exception as exc:  # noqa: BLE001 - provider and tool failures are reported as failed runs
            stop_reason = "agent_error"
            error_type = type(exc).__name__
            usage = asdict(run_usage)
        else:
            try:
                report, verification = verify_report(
                    result.output,
                    store=store,
                    scope=scope,
                    surfaced_evidence_ids=deps.surfaced_evidence_ids,
                )
            except Exception:
                emit(
                    "verification",
                    "failed",
                    "Report verification raised an error",
                    {},
                )
                if existing_run_id is None:
                    with session_scope() as session:
                        fail_run(session, run_id, logfire_trace_id=trace_id)
                if existing_run_id is None:
                    emit(
                        "registry",
                        "failed",
                        "Run marked failed",
                        {"stop_reason": "verification_error"},
                    )
                raise
            emit(
                "verification",
                "completed" if verification.passed else "failed",
                "Citations and report boundaries checked",
                {
                    "passed": verification.passed,
                    "issues": [
                        issue.model_dump(mode="json") for issue in verification.issues
                    ],
                    "surfaced_evidence_ids": sorted(deps.surfaced_evidence_ids),
                    "report_evidence_ids": [
                        item.evidence_id for item in report.evidence
                    ]
                    if report
                    else [],
                },
            )
            if existing_run_id is None:
                with session_scope() as session:
                    if verification.passed:
                        complete_run(session, run_id)
                    else:
                        fail_run(session, run_id, logfire_trace_id=trace_id)
            if existing_run_id is None:
                emit(
                    "registry",
                    "completed" if verification.passed else "failed",
                    "Run state saved",
                    {
                        "status": "completed" if verification.passed else "failed",
                        "stop_reason": "completed"
                        if verification.passed
                        else "verification_failed",
                    },
                )
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
                workflow_steps=workflow_steps,
                surfaced_evidence_ids=sorted(deps.surfaced_evidence_ids),
                logfire_trace_id=trace_id,
                usage=usage,
            )

        emit(
            "agent",
            "failed",
            "Investigator stopped before a verifiable draft",
            {
                "stop_reason": stop_reason,
                "error_type": error_type,
                "failure_detail": failure_detail,
                "usage": usage,
            },
        )
        if existing_run_id is None:
            with session_scope() as session:
                fail_run(session, run_id, logfire_trace_id=trace_id)
        if existing_run_id is None:
            emit(
                "registry",
                "failed",
                "Run marked failed",
                {"status": "failed", "stop_reason": stop_reason},
            )
        return InvestigationExecution(
            run_id=run_id,
            status="failed",
            stop_reason=stop_reason,
            draft=None,
            report=None,
            verification=None,
            tool_steps=list(deps.steps),
            workflow_steps=workflow_steps,
            surfaced_evidence_ids=sorted(deps.surfaced_evidence_ids),
            logfire_trace_id=trace_id,
            usage=usage,
            error_type=error_type,
        )


async def run_investigation(
    request: InvestigationRequest | None,
    *,
    store: TelemetryStore | None = None,
    session_scope: SessionScope = db_utils.get_session,
    model: Model | str | None = None,
    timeout_seconds: float = RUN_TIMEOUT_SECONDS,
    on_step: Callable[[WorkflowStep], None] | None = None,
    detected: DetectedIncident | None = None,
    existing_run_id: uuid.UUID | None = None,
) -> InvestigationExecution:
    """Run at most one investigator at a time in this backend process."""
    queued = INVESTIGATION_GATE.locked()
    gate_steps: list[WorkflowStep] = []
    if queued:
        waiting = WorkflowStep(
            sequence=1,
            stage="guardrail",
            status="running",
            summary="Investigator queued; one report is already running",
            details={"concurrent_investigation_limit": 1},
            elapsed_ms=0,
        )
        gate_steps.append(waiting)
        if on_step is not None:
            on_step(waiting)

    def relay(step: WorkflowStep) -> None:
        if on_step is not None:
            on_step(
                step.model_copy(update={"sequence": step.sequence + len(gate_steps)})
            )

    async with INVESTIGATION_GATE:
        acquired = WorkflowStep(
            sequence=len(gate_steps) + 1,
            stage="guardrail",
            status="completed",
            summary="Investigator slot acquired",
            details={"concurrent_investigation_limit": 1},
            elapsed_ms=0,
        )
        gate_steps.append(acquired)
        if on_step is not None:
            on_step(acquired)
        outcome = await _run_investigation(
            request,
            store=store,
            session_scope=session_scope,
            model=model,
            timeout_seconds=timeout_seconds,
            on_step=relay if on_step is not None else None,
            detected=detected,
            existing_run_id=existing_run_id,
        )
        return replace(
            outcome,
            workflow_steps=gate_steps
            + [
                step.model_copy(update={"sequence": step.sequence + len(gate_steps)})
                for step in outcome.workflow_steps
            ],
        )
