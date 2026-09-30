"""HTTP entry point for the synthetic incident investigation demo."""

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Literal, Never
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.db import db_utils
from backend.db.schemas import IncidentSimulationOutput, LlmRun
from backend.incident_investigation.agent import ToolStep
from backend.incident_investigation.classifier import Classification
from backend.incident_investigation.contracts import (
    DetectedIncident,
    IncidentReport,
    InvestigationRequest,
    VerificationResult,
    WorkflowStep,
)
from backend.incident_investigation.service import (
    InvestigationExecution,
    run_investigation,
)
from backend.incident_investigation.simulation import (
    SimulationExecution,
    run_simulation,
)

router = APIRouter()


class InvestigationResponse(BaseModel):
    run_id: UUID
    status: Literal["completed", "failed"]
    stop_reason: str
    report: IncidentReport | None
    verification: VerificationResult | None
    tool_steps: list[ToolStep]
    workflow_steps: list[WorkflowStep]
    logfire_trace_id: str | None
    usage: dict[str, Any]
    error_type: str | None


class ReportReview(BaseModel):
    decision: Literal["approved", "changes_requested"]
    note: str = Field(default="", max_length=500)
    reviewed_at: datetime


class SimulationResponse(BaseModel):
    run_id: UUID
    status: Literal["completed", "failed"]
    stop_reason: str
    classifications: list[Classification]
    max_reports: int
    detected_incidents: list[DetectedIncident]
    investigations: list[InvestigationResponse]
    workflow_steps: list[WorkflowStep]
    logfire_trace_id: str | None
    error_type: str | None
    review_decisions: dict[str, ReportReview] = Field(default_factory=dict)


class ReportReviewRequest(BaseModel):
    decision: Literal["approved", "changes_requested"]
    note: str = Field(default="", max_length=500)


class SimulationRequest(BaseModel):
    run_id: UUID | None = None
    max_reports: int = Field(default=1, ge=1, le=3)
    replay_delay_ms: int = Field(default=0, ge=0, le=50)


class SimulationRunSummary(BaseModel):
    run_id: UUID
    status: Literal["completed", "failed"]
    stop_reason: str
    report_count: int
    created_at: datetime


def _history_schema_error(exc: SQLAlchemyError) -> Never:
    original = getattr(exc, "orig", None)
    if (
        getattr(original, "pgcode", None) == "42P01"
        or getattr(original, "sqlstate", None) == "42P01"
        or "no such table" in str(original).lower()
    ):
        raise HTTPException(
            status_code=503,
            detail="Incident run history is not set up. Apply database migration 005.",
        ) from exc
    raise exc


@router.get(
    "/agent/incident_investigation/simulations",
    response_model=list[SimulationRunSummary],
)
def list_simulations(
    limit: int = Query(default=10, ge=1, le=50),
) -> list[SimulationRunSummary]:
    try:
        with db_utils.get_session() as session:
            rows = session.execute(
                select(IncidentSimulationOutput, LlmRun)
                .join(LlmRun, LlmRun.id == IncidentSimulationOutput.run_id)
                .order_by(
                    IncidentSimulationOutput.created_at.desc(),
                    IncidentSimulationOutput.run_id.desc(),
                )
                .limit(limit)
            ).all()
            return [
                SimulationRunSummary(
                    run_id=saved.run_id,
                    status=run.status,
                    stop_reason=saved.response_payload["stop_reason"],
                    report_count=len(saved.response_payload["investigations"]),
                    created_at=saved.created_at,
                )
                for saved, run in rows
            ]
    except SQLAlchemyError as exc:
        _history_schema_error(exc)


@router.get(
    "/agent/incident_investigation/simulations/{run_id}",
    response_model=SimulationResponse,
)
def get_simulation(run_id: UUID) -> SimulationResponse:
    try:
        with db_utils.get_session() as session:
            saved = session.get(IncidentSimulationOutput, run_id)
            if saved is None:
                raise HTTPException(status_code=404, detail="Simulation run not found")
            return SimulationResponse.model_validate(saved.response_payload)
    except SQLAlchemyError as exc:
        _history_schema_error(exc)


@router.post(
    "/agent/incident_investigation/simulations/{run_id}/reviews/{incident_id}",
    response_model=SimulationResponse,
)
def review_report(
    run_id: UUID, incident_id: str, request: ReportReviewRequest
) -> SimulationResponse:
    """Record one demo review decision for a verified report in a saved run."""
    note = request.note.strip()
    if request.decision == "changes_requested" and not note:
        raise HTTPException(status_code=422, detail="Explain the requested changes")
    try:
        with db_utils.get_session() as session:
            saved = session.get(IncidentSimulationOutput, run_id, with_for_update=True)
            if saved is None:
                raise HTTPException(status_code=404, detail="Simulation run not found")
            response = SimulationResponse.model_validate(saved.response_payload)
            report_index = next(
                (
                    index
                    for index, incident in enumerate(response.detected_incidents)
                    if incident.incident_id == incident_id
                ),
                None,
            )
            if report_index is None:
                raise HTTPException(status_code=404, detail="Incident report not found")
            investigation = response.investigations[report_index]
            if (
                investigation.report is None
                or investigation.verification is None
                or not investigation.verification.passed
            ):
                raise HTTPException(
                    status_code=409, detail="Only verified reports can be reviewed"
                )
            if incident_id in response.review_decisions:
                raise HTTPException(status_code=409, detail="Report already reviewed")
            response.review_decisions[incident_id] = ReportReview(
                decision=request.decision,
                note=note,
                reviewed_at=datetime.now(timezone.utc),
            )
            saved.response_payload = response.model_dump(mode="json")
            return response
    except SQLAlchemyError as exc:
        _history_schema_error(exc)


@router.post("/agent/incident_investigation", response_model=InvestigationResponse)
async def investigate_incident(request: InvestigationRequest) -> InvestigationResponse:
    try:
        outcome = await run_investigation(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(outcome)


def _response(outcome: InvestigationExecution) -> InvestigationResponse:
    return InvestigationResponse(
        run_id=outcome.run_id,
        status=outcome.status,
        stop_reason=outcome.stop_reason,
        report=outcome.report,
        verification=outcome.verification,
        tool_steps=outcome.tool_steps,
        workflow_steps=outcome.workflow_steps,
        logfire_trace_id=outcome.logfire_trace_id,
        usage=outcome.usage,
        error_type=outcome.error_type,
    )


def _simulation_response(outcome: SimulationExecution) -> SimulationResponse:
    return SimulationResponse(
        run_id=outcome.run_id,
        status=outcome.status,
        stop_reason=outcome.stop_reason,
        classifications=outcome.classifications,
        max_reports=outcome.max_reports,
        detected_incidents=outcome.detected_incidents,
        investigations=[_response(item) for item in outcome.investigations],
        workflow_steps=outcome.workflow_steps,
        logfire_trace_id=outcome.logfire_trace_id,
        error_type=outcome.error_type,
    )


@router.post(
    "/agent/incident_investigation/simulate", response_model=SimulationResponse
)
async def simulate_incident(
    request: SimulationRequest | None = None,
) -> SimulationResponse:
    return _simulation_response(
        await run_simulation(
            run_id=request.run_id if request else None,
            max_reports=request.max_reports if request else 1,
            replay_delay_ms=request.replay_delay_ms if request else 0,
        )
    )


@router.post("/agent/incident_investigation/simulate/stream")
async def stream_simulation(
    request: SimulationRequest | None = None,
) -> StreamingResponse:
    """Stream the log replay, classifier gate, and conditional investigation."""

    async def events():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        def on_step(step: WorkflowStep) -> None:
            event = ("step", step.model_dump(mode="json"))
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is loop:
                queue.put_nowait(event)
            else:
                loop.call_soon_threadsafe(queue.put_nowait, event)

        async def run() -> None:
            try:
                outcome = await run_simulation(
                    run_id=request.run_id if request else None,
                    on_step=on_step,
                    max_reports=request.max_reports if request else 1,
                    replay_delay_ms=request.replay_delay_ms if request else 0,
                )
                await queue.put(
                    ("result", _simulation_response(outcome).model_dump(mode="json"))
                )
            except Exception as exc:  # noqa: BLE001 - stream failures need a terminal event
                await queue.put(("error", {"detail": type(exc).__name__}))

        task = loop.create_task(run())
        try:
            while True:
                event_type, payload = await queue.get()
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                if event_type in {"result", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/agent/incident_investigation/stream")
async def stream_incident(request: InvestigationRequest) -> StreamingResponse:
    """Stream deterministic harness steps before the final response."""

    async def events():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        def on_step(step: WorkflowStep) -> None:
            event = ("step", step.model_dump(mode="json"))
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is loop:
                queue.put_nowait(event)
            else:
                loop.call_soon_threadsafe(queue.put_nowait, event)

        async def run() -> None:
            try:
                outcome = await run_investigation(request, on_step=on_step)
                await queue.put(("result", _response(outcome).model_dump(mode="json")))
            except ValueError as exc:
                await queue.put(("error", {"detail": str(exc)}))
            except Exception as exc:  # noqa: BLE001 - stream failures need a terminal event
                await queue.put(("error", {"detail": type(exc).__name__}))

        task = asyncio.create_task(run())
        try:
            while True:
                event_type, payload = await queue.get()
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                if event_type in {"result", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(events(), media_type="text/event-stream")
