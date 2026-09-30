"""HTTP entry point for the synthetic incident investigation demo."""

import asyncio
import json
from contextlib import suppress
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.incident_investigation.agent import ToolStep
from backend.incident_investigation.contracts import (
    IncidentReport,
    InvestigationRequest,
    VerificationResult,
    WorkflowStep,
)
from backend.incident_investigation.service import (
    InvestigationExecution,
    run_investigation,
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
