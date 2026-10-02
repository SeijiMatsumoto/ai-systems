"""Proposed interfaces only; runtime enforcement and execution remain deferred."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionBudget(Contract):
    """Illustrative server ceilings, not values calibrated by runnable tasks."""

    max_tool_calls: int = Field(default=20, ge=1, le=50)
    max_repair_attempts: int = Field(default=2, ge=0, le=5)
    max_elapsed_seconds: int = Field(default=300, ge=1, le=600)
    max_total_tokens: int = Field(default=20000, ge=1, le=50000)
    max_input_tokens_per_call: int = Field(default=8000, ge=1, le=16000)
    command_timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_observation_chars: int = Field(default=12000, ge=1, le=20000)


class CodingTask(Contract):
    """User request. Permissions and test configuration are resolved by the server."""

    fixture_repo: str = Field(min_length=1, max_length=100)
    base_revision: str = Field(min_length=1, max_length=100)
    issue: str = Field(min_length=1, max_length=8000)


class FixturePolicy(Contract):
    """Trusted fixture registry entry, never accepted from model or user content."""

    read_paths: list[str] = Field(min_length=1, max_length=30)
    write_paths: list[str] = Field(min_length=1, max_length=30)
    editable_validation_targets: list[str] = Field(min_length=1, max_length=10)
    protected_acceptance_targets: list[str] = Field(min_length=1, max_length=10)
    environment_digest: str = Field(min_length=1)
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)


class SearchCodeRequest(Contract):
    """Search the current authorized working tree, not the immutable base snapshot."""

    query: str = Field(min_length=1, max_length=500)
    mode: Literal["lexical", "symbol"] = "lexical"
    max_results: int = Field(default=10, ge=1, le=20)


class ReadFileRequest(Contract):
    path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(default=1, ge=1)
    line_count: int = Field(default=100, ge=1, le=300)


class ReplaceTextRequest(Contract):
    """Atomic exact-match edit; hash must match and old_text must occur once."""

    path: str = Field(min_length=1, max_length=500)
    expected_file_hash: str = Field(min_length=1)
    old_text: str = Field(min_length=1, max_length=15000)
    new_text: str = Field(max_length=15000)


class CreateFileRequest(Contract):
    """Create an authorized, absent path; never overwrite an existing file."""

    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=15000)


class RunValidationRequest(Contract):
    """Only named editable targets are model-facing. No shell text or grader access."""

    target: str = Field(min_length=1, max_length=100)


class ValidationResult(Contract):
    """Produced by the trusted runner, not supplied as a model assertion."""

    target: str
    suite: Literal["baseline", "editable", "protected_acceptance"]
    command: str
    workspace_tree_hash: str
    environment_digest: str
    status: Literal["passed", "failed", "not_run", "timed_out", "environment_error"]
    exit_code: int | None
    tests_collected: int | None = Field(default=None, ge=0)
    summary: str = Field(max_length=12000)


class ToolObservation(Contract):
    """Incrementally recorded runtime result; source locations refer to this tree."""

    step: int = Field(ge=1)
    tool: Literal["search", "read", "replace_text", "create_file", "validate"]
    workspace_tree_hash: str
    status: Literal["ok", "rejected", "failed", "timed_out"]
    content: str = Field(max_length=20000)
    truncated: bool = False


class CodeProposal(Contract):
    """Runtime computes diff and validation evidence; model supplies explanation."""

    base_revision: str
    workspace_tree_hash: str
    changed_paths: list[str]
    unified_diff: str
    baseline_validation: list[ValidationResult]
    final_validation: list[ValidationResult]
    explanation: str
    risks: list[str]
    stop_reason: Literal[
        "ready_for_review",
        "budget_exhausted",
        "blocked",
        "validation_failed",
        "environment_error",
        "cancelled",
    ]
    requires_human_review: Literal[True] = True
