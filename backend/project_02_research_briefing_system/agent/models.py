from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from backend.db.schemas import ResearchRunStatus


class BriefingRequest(BaseModel):
    symbol: str = Field(min_length=1)
    as_of: datetime
    research_question: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    time_horizon: str = Field(min_length=1)


class EvidenceItem(BaseModel):
    evidence_type: Literal["financial", "document"]
    source: str
    reference_id: str
    title: str
    url: str
    content: str | int | float  # Quote or structured financial value
    retrieved_at: datetime
    published_at: datetime | None = None

    # Document evidence
    chunk_id: str | None = None
    chunk_index: int | None = None

    # Structured Financial Evidence
    field_path: str | None = None

    @model_validator(mode="after")
    def validate_evidence_locator(self) -> Self:
        if self.evidence_type == "document" and not self.chunk_id:
            raise ValueError("Document evidence requires chunk_id")

        if self.evidence_type == "document" and not isinstance(self.content, str):
            raise ValueError("Document evidence content must be a quote")

        if self.evidence_type == "financial" and not self.field_path:
            raise ValueError("Financial evidence requires field_path")

        return self


class Finding(BaseModel):
    statement: str
    claim_type: Literal["fact", "calculation", "inference", "scenario"]
    confidence: int = Field(ge=1, le=3)
    evidence: list[EvidenceItem] = Field(min_length=1)


class ResearchBriefing(BaseModel):
    executive_summary: str
    key_findings: list[Finding]
    outlook: str
    limitations: list[str] = Field(default_factory=list)


class GroundingFailure(BaseModel):
    finding_index: int
    reason: str


class VerificationResult(BaseModel):
    unsupported_finding_indexes: list[int] = Field(default_factory=list)
    invalid_evidence_references: list[str] = Field(default_factory=list)
    grounding_failures: list[GroundingFailure] = Field(default_factory=list)
    approval_ready: bool


class ResearchWorkflowResult(BaseModel):
    run_id: UUID
    status: ResearchRunStatus
    briefing: ResearchBriefing | None = None
    verification: VerificationResult | None = None
