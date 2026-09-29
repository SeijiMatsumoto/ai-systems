"""Proposed support conversation shapes; no support runtime yet."""

from typing import Literal

from pydantic import BaseModel, Field


class SupportRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class PolicyCitation(BaseModel):
    policy_id: str
    locator: str
    excerpt: str


class SupportAction(BaseModel):
    action_type: str
    target_id: str
    idempotency_key: str
    state: Literal["proposed", "confirmed", "executed", "rejected"]


class SupportResult(BaseModel):
    answer: str
    citations: list[PolicyCitation]
    proposed_action: SupportAction | None = None
    disposition: Literal["answered", "awaiting_confirmation", "escalated"]
    escalation_reason: str | None = None
