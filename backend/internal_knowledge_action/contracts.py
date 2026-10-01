"""Typed contracts for the internal knowledge assistant."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class KnowledgeQuestionRequest(BaseModel):
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


class RetrievalStep(BaseModel):
    stage: Literal[
        "request_check",
        "access_filter",
        "lexical_search",
        "vector_search",
        "fusion_rerank",
    ]
    detail: str
    source_ids: list[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    fixture_version: str
    embedding_model: str
    persona_id: str
    normalized_question: str
    keyword_signals: list[str]
    authorized_source_ids: list[str]
    lexical_candidates: list[CandidateTrace]
    vector_candidates: list[CandidateTrace]
    ranked_excerpts: list[RankedExcerpt]
    steps: list[RetrievalStep]


class KnowledgeConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=1500)


class KnowledgeAnswerRequest(KnowledgeQuestionRequest):
    """The UI selects a synthetic persona; it cannot provide groups or sources."""

    run_id: UUID | None = None
    conversation_context: list[KnowledgeConversationContext] = Field(
        default_factory=list, max_length=6
    )

    @model_validator(mode="after")
    def limit_conversation_context(self) -> "KnowledgeAnswerRequest":
        if (
            sum(
                len(item.question) + len(item.answer)
                for item in self.conversation_context
            )
            > 8000
        ):
            raise ValueError("Conversation context exceeds the 8000-character limit")
        return self


class SelectedEvidence(BaseModel):
    evidence_id: str
    chunk_id: str
    title: str
    excerpt: str
    locator: SourceLocator


class AnswerClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: bool
    format: Literal["paragraph", "bullet_list", "numbered_list"] = "paragraph"
    claims: list[AnswerClaimDraft] = Field(max_length=3)


class TaskProposalDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: Literal["support_follow_up"]
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=3, max_length=800)
    evidence_ids: list[str] = Field(min_length=1, max_length=2)


class KnowledgeTaskProposal(TaskProposalDraft):
    requester_persona_id: str
    idempotency_key: str


class KnowledgeMockTask(BaseModel):
    task_id: str
    task_type: Literal["support_follow_up"]
    title: str
    description: str
    source_id: str
    idempotency_key: str
    status: Literal["open"] = "open"
    created_at: datetime


class ActionApprover(BaseModel):
    approver_id: str
    label: str
    role: str
    allowed_action_types: list[str]


class ActionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver_id: str = Field(min_length=1, max_length=50)
    decision: Literal["approve", "reject"]


class ActionIntentJudgment(BaseModel):
    model: str
    probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    usage: dict[str, int] = Field(default_factory=dict)


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
        "action_intent_signals",
        "action_intent_classification",
        "action_policy",
        "action_proposal_input",
        "action_proposal_output",
        "action_approval",
        "mock_task_execution",
        "access_filter",
        "lexical_search",
        "vector_search",
        "fusion_rerank",
        "model_input",
        "model_output",
        "citation_check",
        "grounding",
        "action_availability",
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
        "action_intent_unavailable",
        "action_proposal_pending",
        "action_proposal_rejected",
        "action_policy_blocked",
        "action_approval_denied",
        "action_executed",
        "action_proposal_error",
    ]
    request: KnowledgeAnswerRequest
    fixture_version: str | None = None
    embedding_model: str | None = None
    authorized_source_ids: list[str] = Field(default_factory=list)
    evidence: list[SelectedEvidence] = Field(default_factory=list)
    claims: list[AnswerClaimDraft] = Field(default_factory=list)
    available_actions: list[Literal["support_follow_up"]] = Field(default_factory=list)
    action_evidence_ids: list[str] = Field(default_factory=list)
    verification: list[ClaimVerification] = Field(default_factory=list)
    steps: list[KnowledgeStep] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    answer_format: Literal["paragraph", "bullet_list", "numbered_list"] = "paragraph"
    action_status: (
        Literal["pending_approval", "rejected", "blocked", "executed"] | None
    ) = None
    action_proposal: KnowledgeTaskProposal | None = None
    mock_task: KnowledgeMockTask | None = None


class KnowledgeAnswerSummary(BaseModel):
    run_id: UUID
    status: Literal["completed", "failed"]
    stop_reason: str
    persona_id: str
    question: str
    created_at: datetime
