"""Approval policy and idempotent executor for the single synthetic task type."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.schemas import KnowledgeAnswerOutput
from backend.db.schemas import KnowledgeMockTask as TaskRow
from backend.internal_knowledge_action.contracts import (
    ActionDecisionRequest,
    KnowledgeAnswerResult,
    KnowledgeMockTask,
    KnowledgeStep,
    RetrievalFixture,
)

APPROVERS = {
    "jordan-support-lead": {
        "label": "Jordan · Support Lead",
        "role": "support_lead",
        "allowed_action_types": ["support_follow_up"],
    },
    "morgan-engineer": {
        "label": "Morgan · Engineering",
        "role": "engineer",
        "allowed_action_types": [],
    },
}


def _save_steps(
    result: KnowledgeAnswerResult,
    *,
    stage: str,
    status: str,
    summary: str,
    details: dict,
) -> None:
    result.steps = [
        step for step in result.steps if step.stage not in {"persistence", "stop"}
    ]
    result.steps.append(
        KnowledgeStep(
            sequence=0, stage=stage, status=status, summary=summary, details=details
        )
    )
    result.steps.append(
        KnowledgeStep(
            sequence=0,
            stage="persistence",
            status="completed",
            summary="Saved approval decision and current action state",
            details={"run_id": str(result.run_id)},
        )
    )
    result.steps.append(
        KnowledgeStep(
            sequence=0,
            stage="stop",
            status="completed",
            summary=f"Stopped: {result.stop_reason}",
            details={"stop_reason": result.stop_reason},
        )
    )
    result.steps = [
        step.model_copy(update={"sequence": i})
        for i, step in enumerate(result.steps, 1)
    ]


def decide_action(
    session: Session,
    run_id: UUID,
    decision: ActionDecisionRequest,
    fixture: RetrievalFixture,
) -> KnowledgeAnswerResult:
    saved = session.execute(
        select(KnowledgeAnswerOutput)
        .where(KnowledgeAnswerOutput.run_id == run_id)
        .with_for_update()
    ).scalar_one_or_none()
    if saved is None:
        raise LookupError("Knowledge run not found")
    result = KnowledgeAnswerResult.model_validate(saved.response_payload)
    if result.action_proposal is None:
        raise ValueError("This run has no action proposal")

    approver = APPROVERS.get(decision.approver_id)
    authorized_approver = bool(
        approver
        and result.action_proposal.task_type in approver["allowed_action_types"]
    )
    if not authorized_approver:
        result.stop_reason = "action_approval_denied"
        _save_steps(
            result,
            stage="action_approval",
            status="failed",
            summary="Approver is not authorized for this action type",
            details={
                "approver_id": decision.approver_id,
                "decision": decision.decision,
                "allowed": False,
            },
        )
        saved.response_payload = result.model_dump(mode="json")
        return result

    if result.action_status == "executed":
        task = session.execute(
            select(TaskRow).where(TaskRow.run_id == run_id)
        ).scalar_one()
        result.mock_task = KnowledgeMockTask(
            task_id=str(task.id),
            task_type=task.task_type,
            title=task.title,
            description=task.description,
            source_id=task.source_id,
            idempotency_key=task.idempotency_key,
            status="open",
            created_at=task.created_at,
        )
        result.stop_reason = "action_executed"
        _save_steps(
            result,
            stage="mock_task_execution",
            status="completed",
            summary="Repeated approval returned the existing task",
            details={"task_id": str(task.id), "idempotent_replay": True},
        )
        saved.response_payload = result.model_dump(mode="json")
        return result
    if result.action_status != "pending_approval":
        raise ValueError("Action proposal is no longer pending approval")

    if decision.decision == "reject":
        result.action_status = "rejected"
        result.stop_reason = "action_proposal_rejected"
        _save_steps(
            result,
            stage="action_approval",
            status="completed",
            summary="Authorized approver rejected the task proposal",
            details={"approver_id": decision.approver_id, "decision": "reject"},
        )
        saved.response_payload = result.model_dump(mode="json")
        return result

    # Recheck requester membership, current ACL, source revision, and frozen citations.
    proposal = result.action_proposal
    persona = next(
        (p for p in fixture.personas if p.persona_id == proposal.requester_persona_id),
        None,
    )
    access = {a.source_id: a.allowed_groups for a in fixture.acl}
    source_map = {s.source_id: s for s in fixture.sources}
    cited_sources = {
        item.evidence_id: item.locator.source_id for item in result.evidence
    }
    cited_ids_valid = bool(proposal.evidence_ids) and all(
        item in cited_sources
        and cited_sources[item] in result.authorized_source_ids
        and source_map.get(cited_sources[item]) is not None
        and source_map[cited_sources[item]].kind == "ticket"
        and source_map[cited_sources[item]].revision
        == next(
            evidence.locator.revision
            for evidence in result.evidence
            if evidence.evidence_id == item
        )
        for item in proposal.evidence_ids
    )
    scope_still_valid = bool(
        persona
        and "support" in persona.groups
        and cited_ids_valid
        and all(
            set(access.get(cited_sources[item], ())) & set(persona.groups)
            for item in proposal.evidence_ids
        )
    )
    if not scope_still_valid:
        result.action_status = "blocked"
        result.stop_reason = "action_policy_blocked"
        _save_steps(
            result,
            stage="action_policy",
            status="failed",
            summary="Execution blocked because requester scope or source revision changed",
            details={
                "requester_persona_id": proposal.requester_persona_id,
                "source_ids": list(cited_sources.values()),
                "allowed": False,
            },
        )
        saved.response_payload = result.model_dump(mode="json")
        return result

    source_id = cited_sources[proposal.evidence_ids[0]]
    key = proposal.idempotency_key
    task = session.execute(
        select(TaskRow).where(TaskRow.idempotency_key == key)
    ).scalar_one_or_none()
    if task is None:
        task = TaskRow(
            id=uuid4(),
            run_id=run_id,
            idempotency_key=key,
            task_type=proposal.task_type,
            title=proposal.title,
            description=proposal.description,
            source_id=source_id,
        )
        session.add(task)
        session.flush()
    result.action_status = "executed"
    result.stop_reason = "action_executed"
    result.mock_task = KnowledgeMockTask(
        task_id=str(task.id),
        task_type=task.task_type,
        title=task.title,
        description=task.description,
        source_id=task.source_id,
        idempotency_key=task.idempotency_key,
        status="open",
        created_at=task.created_at or datetime.now(UTC),
    )
    _save_steps(
        result,
        stage="mock_task_execution",
        status="completed",
        summary="Created one synthetic support follow-up task",
        details={
            "task_id": str(task.id),
            "idempotency_key": key,
            "source_id": source_id,
            "external_write": False,
        },
    )
    saved.response_payload = result.model_dump(mode="json")
    return result
