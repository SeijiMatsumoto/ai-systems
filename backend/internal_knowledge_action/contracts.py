"""Proposed knowledge and action shapes; no assistant runtime yet."""

from typing import Literal

from pydantic import BaseModel, Field


class AssistantRequest(BaseModel):
    user_id: str = Field(min_length=1)
    question: str = Field(min_length=1)


class SourceCitation(BaseModel):
    source_id: str
    locator: str
    title: str
    excerpt: str


class ProposedAction(BaseModel):
    action_type: str
    arguments: dict[str, str]
    idempotency_key: str
    state: Literal["awaiting_approval", "rejected", "executed"]


class AssistantResult(BaseModel):
    answer: str
    citations: list[SourceCitation]
    proposed_action: ProposedAction | None = None
    limitations: list[str]
