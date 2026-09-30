from datetime import datetime
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.db.schemas import DocumentType, ResearchRunStatus

ScalarValue: TypeAlias = str | int | float | bool | None
ClaimType: TypeAlias = Literal["fact", "calculation", "inference", "scenario"]
ResearchStepStage: TypeAlias = Literal[
    "run",
    "scope",
    "classifier",
    "prefetch",
    "agent",
    "tool",
    "verification",
    "checkpoint",
    "persistence",
]
ResearchStepStatus: TypeAlias = Literal["running", "completed", "failed", "skipped"]


class BriefingRequest(BaseModel):
    symbol: str = Field(min_length=1)
    as_of: datetime
    research_question: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    time_horizon: str = Field(min_length=1)

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        return value


class ResearchQueryPrecheck(BaseModel):
    symbol: str
    normalized_question: str
    symbol_mentioned: bool
    topic_matches: list[str]
    instruction_pattern_matches: list[str]


class SearchDocumentsInput(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    document_type: Literal[DocumentType.FILING, DocumentType.GENERIC]
    top_n: int = Field(default=3, ge=1, le=3)
    published_after: datetime | None = None

    @field_validator("published_after")
    @classmethod
    def require_timezone_when_set(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("published_after must include a timezone")
        return value


class FetchFinancialsInput(BaseModel):
    statement_type: Literal["income", "balance_sheet", "cash_flow"] = "income"
    frequency: Literal["yearly", "quarterly"] = "yearly"
    periods: int = Field(default=4, ge=1, le=8)
    metrics: list[str] | None = Field(default=None, max_length=12)


class SearchWebInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    topic: Literal["news", "general"] = "news"
    limit: int = Field(default=5, ge=1, le=5)
    date_from: datetime | None = None

    @field_validator("date_from")
    @classmethod
    def require_timezone_when_set(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("date_from must include a timezone")
        return value


class InspectWebInput(BaseModel):
    result_ids: list[str] = Field(min_length=1, max_length=3)
    focus: str = Field(min_length=1, max_length=300)


class WebSearchResult(BaseModel):
    result_id: str
    title: str
    source_url: str
    summary: str
    published_at: datetime
    date_precision: Literal["instant", "date"]


class ExtractedWebPage(BaseModel):
    source_url: str
    content: str


class QueryClassification(BaseModel):
    is_relevant: bool
    reasoning: str = Field(max_length=120)


class ResearchQueryJevJudgment(BaseModel):
    model: str
    question_version: int
    relevance_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    instruction_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    usage: dict[str, int]


class ResearchQueryGateDecision(BaseModel):
    outcome: Literal["accept", "reject", "fallback"]
    reason: str
    judgment: ResearchQueryJevJudgment


class WebPassageJudgment(BaseModel):
    evidence_id: str
    model: str
    relevance_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    novelty_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    usage: dict[str, int]


class WebSourceDisposition(BaseModel):
    evidence_id: str
    title: str
    url: str | None = None
    outcome: Literal["cited", "excluded", "review_failed"]
    reason: str
    relevance_probability: float | None = None
    novelty_probability: float | None = None


class GroundingClassification(BaseModel):
    is_supported: bool
    reasoning: str


class FindingRevision(BaseModel):
    action: Literal["revise", "drop_duplicate"]
    statement: str | None = Field(default=None, min_length=1)
    claim_type: ClaimType | None = None
    confidence: int | None = Field(default=None, ge=1, le=3)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "FindingRevision":
        revision_fields = (self.statement, self.claim_type, self.confidence)
        if self.action == "revise" and any(value is None for value in revision_fields):
            raise ValueError(
                "statement, claim_type, and confidence are required when revising"
            )
        if self.action == "drop_duplicate" and any(
            value is not None for value in revision_fields
        ):
            raise ValueError(
                "revision fields must be omitted when dropping a duplicate"
            )
        return self


class BriefingNarrative(BaseModel):
    executive_summary: str = Field(min_length=1)
    outlook: str = Field(min_length=1)


class ResearchWorkflowStep(BaseModel):
    run_id: UUID
    sequence: int = Field(ge=1)
    stage: ResearchStepStage
    status: ResearchStepStatus
    summary: str = Field(min_length=1)
    details: dict[str, object] = Field(default_factory=dict)
    recorded_at: datetime


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


class WebFindingSuggestion(BaseModel):
    finding: DraftFinding | None = None
    reason: str = Field(min_length=1, max_length=240)


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
