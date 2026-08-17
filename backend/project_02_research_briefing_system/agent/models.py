from datetime import datetime
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, Field

from backend.db.schemas import DocumentType, ResearchRunStatus

ScalarValue: TypeAlias = str | int | float | bool | None
ClaimType: TypeAlias = Literal["fact", "calculation", "inference", "scenario"]


class BriefingRequest(BaseModel):
    symbol: str = Field(min_length=1)
    as_of: datetime
    research_question: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    time_horizon: str = Field(min_length=1)


class EvidenceCandidate(BaseModel):
    """Common identity fields for evidence exposed to the agent."""

    evidence_id: str = Field(min_length=1)
    reference_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str | None = None
    retrieved_at: datetime
    published_at: datetime | None = None


class DocumentEvidence(EvidenceCandidate):
    """An exact passage in any row represented by the Document table."""

    evidence_type: Literal["document"] = "document"
    document_type: DocumentType
    content_quality: Literal["full_text", "snippet"]
    document_id: str
    chunk_id: str
    chunk_index: int
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    content_hash: str = Field(min_length=64, max_length=64)
    quote: str = Field(min_length=1)


class FinancialEvidence(EvidenceCandidate):
    """A scalar value at a deterministic path in structured financial data."""

    evidence_type: Literal["financial"] = "financial"
    source: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    value: ScalarValue
    period_end: str | None = None


EvidenceRecord: TypeAlias = Annotated[
    DocumentEvidence | FinancialEvidence,
    Field(discriminator="evidence_type"),
]


class DraftFinding(BaseModel):
    """Agent-authored claim containing references, not copied source content."""

    statement: str = Field(min_length=1)
    claim_type: ClaimType
    confidence: int = Field(ge=1, le=3)
    evidence_ids: list[str] = Field(min_length=1)


class DraftResearchBriefing(BaseModel):
    """The agent output. Python resolves evidence IDs into final evidence records."""

    executive_summary: str
    key_findings: list[DraftFinding] = Field(min_length=1)
    outlook: str
    limitations: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    statement: str
    claim_type: ClaimType
    confidence: int = Field(ge=1, le=3)
    evidence: list[EvidenceRecord] = Field(default_factory=list)


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
