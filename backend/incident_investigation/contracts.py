"""Investigation request, cited report, and verification result shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.incident_investigation.telemetry import CoverageGap


class InvestigationRequest(BaseModel):
    service: str = Field(min_length=1)
    alert_id: str = Field(min_length=1)
    window_start: datetime
    window_end: datetime


class TelemetryEvidence(BaseModel):
    evidence_id: str
    source: Literal["log", "metric", "trace", "change", "alert"]
    service: str
    locator: str
    observed_at: datetime
    excerpt: str


class IncidentClaim(BaseModel):
    statement: str
    kind: Literal["fact", "correlation", "hypothesis"]
    evidence_ids: list[str]


class IncidentReport(BaseModel):
    timeline: list[IncidentClaim]
    likely_causes: list[IncidentClaim]
    unknowns: list[str]
    next_checks: list[str]
    coverage_gaps: list[CoverageGap]
    evidence: list[TelemetryEvidence]
    review_required: bool = True


class VerificationIssue(BaseModel):
    code: Literal[
        "empty_report",
        "invalid_kind",
        "unknown_evidence",
        "not_surfaced",
        "outside_scope",
    ]
    path: str
    evidence_id: str | None = None


class VerificationResult(BaseModel):
    passed: bool
    issues: list[VerificationIssue]


class WorkflowStep(BaseModel):
    sequence: int
    stage: Literal["scope", "registry", "agent", "tool", "verification"]
    status: Literal["completed", "failed", "running"]
    summary: str
    details: dict[str, Any]
    elapsed_ms: int
