"""Labeled classifier inputs and provider observations for repeatable evaluations."""

from typing import Literal

from pydantic import Field

from ..contracts import ConversationContext, Intent, IntentJudgment, Record


class Expected(Record):
    intent: Intent
    branch: Literal["read_only", "proposal", "human_review", "clarify", "unsupported"]


class ClassifierCase(Record):
    name: str
    split: Literal["development", "holdout"]
    category: str
    source: str
    message: str = Field(min_length=1, max_length=2000)
    context: ConversationContext
    history: list[dict]
    tasks: list[dict]
    expected: Expected


class Observation(Record):
    name: str
    judgment: IntentJudgment | None = None
    error: str | None = None
    elapsed_seconds: float = 0
