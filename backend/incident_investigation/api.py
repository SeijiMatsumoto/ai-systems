"""HTTP entry point for the synthetic incident investigation demo."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.incident_investigation.agent import ToolStep
from backend.incident_investigation.contracts import (
    IncidentReport,
    InvestigationRequest,
    VerificationResult,
)
from backend.incident_investigation.service import run_investigation

router = APIRouter()


class InvestigationResponse(BaseModel):
    run_id: UUID
    status: Literal["completed", "failed"]
    stop_reason: str
    report: IncidentReport | None
    verification: VerificationResult | None
    tool_steps: list[ToolStep]
    logfire_trace_id: str | None
    usage: dict[str, Any]
    error_type: str | None


@router.post("/agent/incident_investigation", response_model=InvestigationResponse)
async def investigate_incident(request: InvestigationRequest) -> InvestigationResponse:
    try:
        outcome = await run_investigation(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InvestigationResponse(
        run_id=outcome.run_id,
        status=outcome.status,
        stop_reason=outcome.stop_reason,
        report=outcome.report,
        verification=outcome.verification,
        tool_steps=outcome.tool_steps,
        logfire_trace_id=outcome.logfire_trace_id,
        usage=outcome.usage,
        error_type=outcome.error_type,
    )
