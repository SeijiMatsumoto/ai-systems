"""One bounded Jev judgment over a deterministic incident candidate."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from typing import Literal

import logfire
from pydantic import BaseModel, Field
from typesafe_sdk import AsyncTypeSafeClient, Noul

from backend import observability  # noqa: F401 - configure Logfire and load .env

JEV_MODEL = "jev-latest"
QUESTION_VERSION = 1
QUESTION = (
    "Do these observed log and metric signals indicate an active, user-impacting "
    "service incident that warrants investigation, rather than errors handled "
    "by a successful fallback or short retry?"
)
YES_CRITERION = (
    "Sustained user-facing failures or degraded requests require investigation."
)
NO_CRITERION = (
    "Errors are contained by fallback or retry, without user-facing degradation."
)
INCIDENT_THRESHOLD = 0.75
NONINCIDENT_THRESHOLD = 0.35
CLASSIFIER_TIMEOUT_SECONDS = 10


class CandidateSummary(BaseModel):
    cluster_id: str
    trigger_log_id: str
    trigger_service: str
    observed_at: datetime
    services: list[str]
    distinct_error_requests_last_5m: int
    log_levels: dict[str, int]
    representative_messages: list[str] = Field(max_length=8)
    log_evidence_ids: list[str] = Field(max_length=30)
    latest_error_rates: dict[str, float]
    metric_evidence_ids: list[str]


class JevJudgment(BaseModel):
    model: str
    question_version: int
    probability: float = Field(ge=0, le=1)
    usage: dict[str, int]


class Classification(BaseModel):
    summary: CandidateSummary
    outcome: Literal[
        "incident", "not_incident", "needs_review", "classifier_unavailable"
    ]
    judgment: JevJudgment | None
    error_type: str | None = None


def decide(summary: CandidateSummary, judgment: JevJudgment) -> Classification:
    probability = judgment.probability
    if not math.isfinite(probability):
        raise ValueError("Jev probability must be finite")
    outcome: Literal["incident", "not_incident", "needs_review"]
    if probability >= INCIDENT_THRESHOLD:
        outcome = "incident"
    elif probability <= NONINCIDENT_THRESHOLD:
        outcome = "not_incident"
    else:
        outcome = "needs_review"
    return Classification(summary=summary, outcome=outcome, judgment=judgment)


async def classify_candidate(summary: CandidateSummary) -> JevJudgment:
    """Call TypeSafe with Logfire spans around the complete external request."""
    state = summary.model_dump(mode="json")
    with logfire.span(
        "Jev classify incident candidate {cluster_id}",
        cluster_id=summary.cluster_id,
        trigger_log_id=summary.trigger_log_id,
        model=JEV_MODEL,
        question_version=QUESTION_VERSION,
        state=state,
        question=QUESTION,
    ) as span:
        try:
            async with asyncio.timeout(CLASSIFIER_TIMEOUT_SECONDS):
                async with AsyncTypeSafeClient(
                    timeout=CLASSIFIER_TIMEOUT_SECONDS
                ) as client:
                    response = await client.system_one(
                        model=JEV_MODEL,
                        state=state,
                        questions={
                            "active_incident": Noul(
                                instructions=QUESTION,
                                criteria={"true": YES_CRITERION, "false": NO_CRITERION},
                            )
                        },
                    )
            answer = response.nouls["active_incident"]
            judgment = JevJudgment(
                model=response.model,
                question_version=QUESTION_VERSION,
                probability=answer.noul,
                usage=response.usage.model_dump(),
            )
            span.set_attribute("jev.probability", judgment.probability)
            span.set_attribute("jev.output_model", judgment.model)
            span.set_attribute(
                "jev.input_tokens", judgment.usage.get("input_tokens", 0)
            )
            return judgment
        except Exception as exc:
            span.set_attribute("jev.error_type", type(exc).__name__)
            raise
