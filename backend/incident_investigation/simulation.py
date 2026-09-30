"""Replay logs, judge candidates, and investigate accepted incidents."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

import logfire
from pydantic import TypeAdapter
from pydantic_ai.models import Model
from sqlalchemy.orm import Session

from backend.db import db_utils
from backend.db.llm_runs import complete_run, create_run, fail_run, start_run
from backend.db.schemas import IncidentSimulationOutput
from backend.incident_investigation.classifier import (
    CLASSIFIER_TIMEOUT_SECONDS,
    INCIDENT_THRESHOLD,
    JEV_MODEL,
    NONINCIDENT_THRESHOLD,
    QUESTION,
    QUESTION_VERSION,
    CandidateSummary,
    Classification,
    JevJudgment,
    classify_candidate,
    decide,
)
from backend.incident_investigation.contracts import DetectedIncident, WorkflowStep
from backend.incident_investigation.detection import (
    REPLAY_FIXTURE_DIR,
    ReplayStep,
    replay_logs,
)
from backend.incident_investigation.service import (
    InvestigationExecution,
    run_investigation,
)
from backend.incident_investigation.telemetry import TelemetryStore
from backend.observability import EXPORT_ENABLED

SessionScope = Callable[[], AbstractContextManager[Session]]
Classifier = Callable[[CandidateSummary], Awaitable[JevJudgment]]
MAX_REPORTS_HARD_LIMIT = 3
LOOKBACK = timedelta(minutes=20)


@dataclass(frozen=True)
class SimulationExecution:
    run_id: uuid.UUID
    status: Literal["completed", "failed"]
    stop_reason: str
    classifications: list[Classification]
    max_reports: int
    detected_incidents: list[DetectedIncident]
    investigations: list[InvestigationExecution]
    workflow_steps: list[WorkflowStep] = field(default_factory=list)
    logfire_trace_id: str | None = None
    error_type: str | None = None


SIMULATION_ADAPTER = TypeAdapter(SimulationExecution)


def build_summary(
    trigger: ReplayStep, seen_steps: list[ReplayStep], store: TelemetryStore
) -> CandidateSummary:
    """Use only replayed logs and metrics observable at the trigger instant."""
    cutoff = trigger.log.observed_at
    cluster_logs = [
        step.log
        for step in seen_steps
        if step.group_id in trigger.cluster_group_ids
        and step.log.level == "ERROR"
        and step.log.observed_at <= cutoff
    ]
    latest_metrics = {}
    for point in store.metrics:
        if (
            point.service in trigger.cluster_services
            and point.metric == "error_rate"
            and cutoff - timedelta(minutes=2) <= point.observed_at <= cutoff
            and (
                point.service not in latest_metrics
                or point.observed_at > latest_metrics[point.service].observed_at
            )
        ):
            latest_metrics[point.service] = point
    return CandidateSummary(
        cluster_id=trigger.cluster_id or "",
        trigger_log_id=trigger.log.evidence_id,
        trigger_service=trigger.log.service,
        observed_at=cutoff,
        services=trigger.cluster_services,
        distinct_error_requests_last_5m=trigger.distinct_error_requests,
        log_levels=dict(Counter(log.level for log in cluster_logs)),
        representative_messages=sorted({log.message for log in cluster_logs})[:8],
        log_evidence_ids=[log.evidence_id for log in cluster_logs[-30:]],
        latest_error_rates={
            service: point.value for service, point in latest_metrics.items()
        },
        metric_evidence_ids=[
            latest_metrics[service].evidence_id for service in sorted(latest_metrics)
        ],
    )


def detected_from(summary: CandidateSummary, store: TelemetryStore) -> DetectedIncident:
    start = max(store.manifest.window_start, summary.observed_at - LOOKBACK)
    return DetectedIncident(
        incident_id=f"detected-{summary.cluster_id}-{summary.observed_at:%Y%m%d%H%M%S}",
        cluster_id=summary.cluster_id,
        trigger_log_id=summary.trigger_log_id,
        service=summary.trigger_service,
        observed_at=summary.observed_at,
        window_start=start,
        window_end=summary.observed_at,
    )


async def run_simulation(
    *,
    run_id: uuid.UUID | None = None,
    store: TelemetryStore | None = None,
    classifier: Classifier = classify_candidate,
    session_scope: SessionScope = db_utils.get_session,
    investigator_model: Model | str | None = None,
    on_step: Callable[[WorkflowStep], None] | None = None,
    max_reports: int = 1,
    replay_delay_ms: int = 0,
) -> SimulationExecution:
    if not 1 <= max_reports <= MAX_REPORTS_HARD_LIMIT:
        raise ValueError(f"max_reports must be between 1 and {MAX_REPORTS_HARD_LIMIT}")
    if not 0 <= replay_delay_ms <= 50:
        raise ValueError("replay_delay_ms must be between 0 and 50")
    store = store or TelemetryStore(REPLAY_FIXTURE_DIR)
    if store.manifest.alert is not None:
        raise ValueError("simulation fixture must not contain a prewritten alert")
    started_at = time.perf_counter()
    steps: list[WorkflowStep] = []
    seen: list[ReplayStep] = []
    classifications: list[Classification] = []
    detected_incidents: list[DetectedIncident] = []
    investigations: list[InvestigationExecution] = []
    error_type: str | None = None
    stop_reason = "no_incident"

    def emit(
        stage: Literal[
            "replay",
            "guardrail",
            "classifier",
            "scope",
            "registry",
            "agent",
            "tool",
            "verification",
        ],
        status: Literal["completed", "failed", "running"],
        summary: str,
        details: dict[str, Any],
    ) -> None:
        step = WorkflowStep(
            sequence=len(steps) + 1,
            stage=stage,
            status=status,
            summary=summary,
            details=details,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        )
        steps.append(step)
        if on_step:
            on_step(step)

    with session_scope() as session:
        run_id = create_run(session, "incident_investigation", run_id=run_id).id
    emit("registry", "completed", "Simulation run created", {"run_id": str(run_id)})

    with logfire.span("Incident log simulation {run_id}", run_id=str(run_id)) as span:
        context = span.get_span_context()
        trace_id = (
            f"{context.trace_id:032x}"
            if EXPORT_ENABLED and context is not None and context.is_valid
            else None
        )
        try:
            with session_scope() as session:
                start_run(session, run_id, logfire_trace_id=trace_id)
            emit(
                "registry",
                "running",
                "Simulation run started",
                {"logfire_trace_id": trace_id},
            )
            for replay_step in replay_logs(store):
                seen.append(replay_step)
                emit(
                    "replay",
                    "completed",
                    f"{replay_step.log.service} ERROR log grouped"
                    if replay_step.log.level == "ERROR"
                    else f"{replay_step.log.service} {replay_step.log.level} log observed",
                    replay_step.model_dump(mode="json"),
                )
                if replay_delay_ms:
                    await asyncio.sleep(replay_delay_ms / 1000)
                elif replay_step.sequence % 8 == 0:
                    await asyncio.sleep(0)  # let the SSE response flush replay steps
                if replay_step.decision != "candidate":
                    continue
                emit(
                    "guardrail",
                    "completed",
                    "Candidate passed deterministic error threshold",
                    {
                        "cluster_id": replay_step.cluster_id,
                        "distinct_error_requests": replay_step.distinct_error_requests,
                        "reason": replay_step.reason,
                    },
                )
                summary = build_summary(replay_step, seen, store)
                emit(
                    "classifier",
                    "running",
                    "Jev judgment requested",
                    {
                        "model": JEV_MODEL,
                        "question_version": QUESTION_VERSION,
                        "question": QUESTION,
                        "state": summary.model_dump(mode="json"),
                        "timeout_seconds": CLASSIFIER_TIMEOUT_SECONDS,
                    },
                )
                try:
                    judgment = await classifier(summary)
                    classification = decide(summary, judgment)
                except Exception as exc:  # noqa: BLE001 - provider failures are explicit run outcomes
                    error_type = type(exc).__name__
                    classification = Classification(
                        summary=summary,
                        outcome="classifier_unavailable",
                        judgment=None,
                        error_type=error_type,
                    )
                classifications.append(classification)
                emit(
                    "classifier",
                    "failed"
                    if classification.outcome == "classifier_unavailable"
                    else "completed",
                    f"Candidate classified {classification.outcome.replace('_', ' ')}",
                    {
                        **classification.model_dump(mode="json"),
                        "incident_threshold": INCIDENT_THRESHOLD,
                        "nonincident_threshold": NONINCIDENT_THRESHOLD,
                    },
                )
                if classification.outcome == "classifier_unavailable":
                    stop_reason = "classifier_unavailable"
                    break
                if classification.outcome == "needs_review" and not detected_incidents:
                    stop_reason = "needs_review"
                if classification.outcome != "incident":
                    continue
                if len(investigations) >= max_reports:
                    emit(
                        "guardrail",
                        "completed",
                        "Additional incident held for review; investigation budget reached",
                        {"max_reports": max_reports},
                    )
                    continue
                detected = detected_from(summary, store)
                detected_incidents.append(detected)
                snapshot = store.snapshot(detected.observed_at)
                emit(
                    "scope",
                    "completed",
                    "Detected incident scoped to a trigger-time telemetry snapshot",
                    {
                        "incident": detected.model_dump(mode="json"),
                        "snapshot_records": {
                            "logs": len(snapshot.logs),
                            "metrics": len(snapshot.metrics),
                            "traces": len(snapshot.spans),
                            "changes": len(snapshot.changes),
                        },
                    },
                )

                def relay(step: WorkflowStep) -> None:
                    emit(step.stage, step.status, step.summary, step.details)

                investigation = await run_investigation(
                    None,
                    detected=detected,
                    existing_run_id=run_id,
                    store=snapshot,
                    session_scope=session_scope,
                    model=investigator_model,
                    on_step=relay,
                )
                investigations.append(investigation)
                stop_reason = investigation.stop_reason
                if investigation.status == "failed":
                    break

            failed = stop_reason in {
                "classifier_unavailable",
                "timeout",
                "budget_exhausted",
                "agent_error",
                "verification_failed",
            }
            final_step = WorkflowStep(
                sequence=len(steps) + 1,
                stage="registry",
                status="failed" if failed else "completed",
                summary="Simulation run finished",
                details={
                    "status": "failed" if failed else "completed",
                    "stop_reason": stop_reason,
                },
                elapsed_ms=round((time.perf_counter() - started_at) * 1000),
            )
            steps.append(final_step)
            execution = SimulationExecution(
                run_id=run_id,
                status="failed" if failed else "completed",
                stop_reason=stop_reason,
                classifications=classifications,
                max_reports=max_reports,
                detected_incidents=detected_incidents,
                investigations=investigations,
                workflow_steps=steps,
                logfire_trace_id=trace_id,
                error_type=error_type,
            )
            with session_scope() as session:
                if failed:
                    fail_run(session, run_id, logfire_trace_id=trace_id)
                else:
                    complete_run(session, run_id)
                session.add(
                    IncidentSimulationOutput(
                        run_id=run_id,
                        response_payload=SIMULATION_ADAPTER.dump_python(
                            execution, mode="json"
                        ),
                    )
                )
            if on_step:
                on_step(final_step)
            return execution
        except BaseException:
            with session_scope() as session:
                fail_run(session, run_id, logfire_trace_id=trace_id)
            raise
