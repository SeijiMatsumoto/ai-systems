"""Contracts for the synthetic, read-only knowledge retrieval preview."""

from typing import Literal

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
