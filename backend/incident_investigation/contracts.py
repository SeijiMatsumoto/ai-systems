"""Investigation request and proposed final report shapes.

The local draft agent lives in agent.py; report verification is not implemented yet.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class InvestigationRequest(BaseModel):
    service: str = Field(min_length=1)
    alert_id: str = Field(min_length=1)
    window_start: datetime
    window_end: datetime


class TelemetryEvidence(BaseModel):
    evidence_id: str
    source: Literal["log", "metric", "trace", "deployment", "alert"]
    locator: str
    observed_at: datetime


class IncidentClaim(BaseModel):
    statement: str
    kind: Literal["fact", "correlation", "hypothesis"]
    evidence_ids: list[str]


class IncidentReport(BaseModel):
    timeline: list[IncidentClaim]
    likely_causes: list[IncidentClaim]
    unknowns: list[str]
    evidence: list[TelemetryEvidence]
    review_required: bool = True
