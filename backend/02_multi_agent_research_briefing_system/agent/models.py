from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BriefingRequest(BaseModel):
    symbol: str = Field(min_length=1)
    as_of: datetime
    research_question: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    time_horizon: str = Field(min_length=1)


class EvidenceItem(BaseModel):
    source: str
    reference_id: str
    title: str
    url: str
    content: str
    retrieved_at: datetime
    published_at: datetime | None = None
    chunk_id: str | None = None
    chunk_index: int | None = None


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


class VerificationResult(BaseModel):
    unsupported_finding_indexes: list[int] = Field(default_factory=list)
    invalid_evidence_references: list[str] = Field(default_factory=list)
    stale_evidence_references: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    approval_ready: bool
