"""Proposed coding task and review artifact shapes; no execution runtime yet."""

from typing import Literal

from pydantic import BaseModel, Field


class CodingTask(BaseModel):
    fixture_repo: str = Field(min_length=1)
    issue: str = Field(min_length=1)
    allowed_paths: list[str] = Field(min_length=1)


class ValidationResult(BaseModel):
    command: str
    status: Literal["passed", "failed", "not_run"]
    summary: str


class CodeProposal(BaseModel):
    changed_paths: list[str]
    unified_diff: str
    validation: list[ValidationResult]
    explanation: str
    risks: list[str]
    requires_human_review: bool = True
