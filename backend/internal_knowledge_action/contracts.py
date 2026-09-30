"""Contracts for the synthetic, read-only knowledge retrieval preview."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DemoPersona(BaseModel):
    persona_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    groups: tuple[str, ...] = Field(min_length=1)


class SourceRecord(BaseModel):
    source_id: str = Field(min_length=1)
    kind: Literal["document", "ticket", "policy"]
    title: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    body: str = Field(min_length=1)


class SourceACL(BaseModel):
    source_id: str = Field(min_length=1)
    allowed_groups: tuple[str, ...] = Field(min_length=1)


class RetrievalFixture(BaseModel):
    version: str = Field(min_length=1)
    personas: tuple[DemoPersona, ...] = Field(min_length=1)
    sources: tuple[SourceRecord, ...] = Field(min_length=1)
    acl: tuple[SourceACL, ...] = Field(min_length=1)


class RetrievalPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1, max_length=500)


class SourceLocator(BaseModel):
    source_id: str
    revision: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class IndexedSource(BaseModel):
    source_id: str
    kind: Literal["document", "ticket", "policy"]
    title: str
    revision: str
    content_hash: str
    allowed_groups: tuple[str, ...]


class IndexedChunk(BaseModel):
    chunk_id: str
    source_id: str
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    embedding: tuple[float, ...] = Field(min_length=1)


class IndexSnapshot(BaseModel):
    fixture_version: str
    embedding_model: str
    sources: tuple[IndexedSource, ...]
    chunks: tuple[IndexedChunk, ...]


class IndexBuildReport(BaseModel):
    fixture_version: str
    embedding_model: str
    added_sources: list[str]
    updated_sources: list[str]
    unchanged_sources: list[str]
    removed_sources: list[str]
    acl_only_sources: list[str]
    embedded_chunks: int
    total_chunks: int


class IndexStatus(BaseModel):
    ready: bool
    fixture_version: str
    embedding_model: str | None
    source_count: int
    chunk_count: int


class CandidateTrace(BaseModel):
    chunk_id: str
    source_id: str
    rank: int = Field(ge=1)
    score: float


class RankedExcerpt(BaseModel):
    chunk_id: str
    title: str
    kind: Literal["document", "ticket", "policy"]
    excerpt: str
    locator: SourceLocator
    lexical_rank: int | None
    vector_rank: int | None
    rerank_score: float


class PreviewStep(BaseModel):
    stage: Literal[
        "request_check",
        "access_filter",
        "lexical_search",
        "vector_search",
        "fusion_rerank",
        "stop",
    ]
    detail: str
    source_ids: list[str] = Field(default_factory=list)


class RetrievalPreview(BaseModel):
    fixture_version: str
    embedding_model: str
    persona_id: str
    normalized_question: str
    keyword_signals: list[str]
    authorized_source_ids: list[str]
    lexical_candidates: list[CandidateTrace]
    vector_candidates: list[CandidateTrace]
    ranked_excerpts: list[RankedExcerpt]
    steps: list[PreviewStep]
    stop_reason: Literal["retrieval_preview_only"] = "retrieval_preview_only"


class KnowledgeAnswerRequest(RetrievalPreviewRequest):
    """The UI selects a synthetic persona; it cannot provide groups or sources."""

    run_id: UUID | None = None


class SelectedEvidence(BaseModel):
    evidence_id: str
    chunk_id: str
    title: str
    excerpt: str
    locator: SourceLocator


class AnswerClaimDraft(BaseModel):
    statement: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)


class AnswerDraft(BaseModel):
    abstain: bool
    claims: list[AnswerClaimDraft] = Field(max_length=3)


class GroundingJudgment(BaseModel):
    model: str
    question_version: int
    probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    usage: dict[str, int] = Field(default_factory=dict)


class ClaimVerification(BaseModel):
    claim_index: int
    passed: bool
    reason: str
    judgment: GroundingJudgment | None = None


class KnowledgeStep(BaseModel):
    sequence: int
    stage: Literal[
        "request_check",
        "access_filter",
        "lexical_search",
        "vector_search",
        "fusion_rerank",
        "model_input",
        "model_output",
        "citation_check",
        "grounding",
        "persistence",
        "stop",
    ]
    status: Literal["running", "completed", "failed", "skipped"]
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class KnowledgeAnswerResult(BaseModel):
    run_id: UUID
    status: Literal["completed", "failed"]
    stop_reason: Literal[
        "answered",
        "no_relevant_passage",
        "model_abstained",
        "citation_rejected",
        "grounding_rejected",
        "grounding_unavailable",
        "answer_model_error",
        "retrieval_error",
        "read_only_action_request",
    ]
    request: KnowledgeAnswerRequest
    fixture_version: str | None = None
    embedding_model: str | None = None
    authorized_source_ids: list[str] = Field(default_factory=list)
    evidence: list[SelectedEvidence] = Field(default_factory=list)
    claims: list[AnswerClaimDraft] = Field(default_factory=list)
    verification: list[ClaimVerification] = Field(default_factory=list)
    steps: list[KnowledgeStep] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None


class KnowledgeAnswerSummary(BaseModel):
    run_id: UUID
    status: Literal["completed", "failed"]
    stop_reason: str
    persona_id: str
    question: str
    created_at: datetime
