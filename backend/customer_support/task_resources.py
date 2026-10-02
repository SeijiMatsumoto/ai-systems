"""Task-local evidence reuse and cumulative deterministic resource checks."""

from .contracts import SavedPolicyEvidence, TaskResourceLimits, TaskResources

TASK_LIMITS = TaskResourceLimits()


class TaskBudgetReached(Exception):
    pass


def reported_tokens(usage):
    return sum(
        max(0, int(value.get("input_tokens", 0)))
        + max(0, int(value.get("output_tokens", 0)))
        for value in usage.values()
    )


def resource_totals(previous, usage, steps):
    return TaskResources(
        executions=previous.executions + 1,
        tokens=previous.tokens + reported_tokens(usage),
        tool_calls=previous.tool_calls
        + sum(step.stage == "tool_request" for step in steps),
    )


def policy_reuse(saved, store):
    """Exact current passage equality proves provenance, not semantic relevance."""
    accepted, rejected = [], []
    for item in saved:
        evidence = item.evidence
        current = next(
            (
                p
                for p in store.fixture.policies
                if p.policy_id == evidence.source_id
                and f"{p.revision}:{p.locator}" == evidence.locator
            ),
            None,
        )
        if (
            current is None
            or current.effective_on > store.fixture.scenario_date
            or current.text != evidence.text
        ):
            rejected.append(
                {
                    "source_run_id": item.source_run_id,
                    "source_id": evidence.source_id,
                    "reason": "not_current_exact_passage",
                }
            )
        else:
            accepted.append(item)
    return accepted, rejected


def saved_policies(previous, response):
    by_locator = {
        (item.evidence.source_id, item.evidence.locator): item for item in previous
    }
    for evidence in response.evidence:
        if evidence.kind == "policy":
            by_locator[(evidence.source_id, evidence.locator)] = SavedPolicyEvidence(
                source_run_id=response.run_id, evidence=evidence
            )
    return tuple(list(by_locator.values())[-12:])


def restore_policy(saved, store, state, add, step):
    accepted, rejected = policy_reuse(saved, store)
    reused = [
        add(
            "policy", item.evidence.source_id, item.evidence.locator, item.evidence.text
        )
        for item in accepted
    ]
    step(
        "policy_reuse_check",
        reused=[
            {
                "source_run_id": item.source_run_id,
                "source_evidence_id": item.evidence.evidence_id,
                "current_evidence_id": evidence["evidence_id"],
            }
            for item, evidence in zip(accepted, reused)
        ],
        invalidated=rejected,
        scope="same task; exact currently effective passage",
        semantic_relevance="requires model judgment and grounding",
    )
    if reused:
        state["observations"].append(
            {"tool": {"name": "saved_policy", "arguments": {}}, "results": reused}
        )
        state["required_evidence"] = (
            "Fresh selected order facts (if present) and checked saved policy are available. Use relevant evidence to answer or propose directly; search only when these passages do not cover the request."
        )


def remaining_resources(checkpoint, run_tokens, run_tools):
    prior = checkpoint.resources if checkpoint else TaskResources()
    return (
        prior,
        min(run_tokens, max(0, TASK_LIMITS.tokens - prior.tokens)),
        min(run_tools, max(0, TASK_LIMITS.tool_calls - prior.tool_calls)),
    )


def task_budget_exhausted(prior, usage, token_limit):
    return (
        prior.executions >= TASK_LIMITS.executions
        or reported_tokens(usage) >= token_limit
    )


def bound_proposal_result(
    usage, token_limit, disposition, answer, reason, evidence_ids, operation
):
    if reported_tokens(usage) > token_limit and operation is not None:
        return (
            "handoff_needed",
            "This request has reached its support limit. Please contact our support team.",
            "task_resource_budget",
            (),
            None,
        )
    return disposition, answer, reason, evidence_ids, operation


def ensure_task_budget(prior, usage, token_limit):
    if task_budget_exhausted(prior, usage, token_limit):
        raise TaskBudgetReached("Task resource limit reached")
