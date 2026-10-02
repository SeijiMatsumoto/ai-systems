"""Conversation routing chooses context, never authorization or execution."""

import asyncio
import json
import re

from .contracts import SupportRequest, TaskRoute
from .providers import ModelBoundaryFailure
from .service import is_confirmation_reply, precheck
from .task_resources import TASK_LIMITS


def kind_signal(message):
    if re.search(r"\b(policy|rules)\b", message, re.IGNORECASE) and not re.search(
        r"\b(want|need|please|submit|create)\b|\brequest (?:a |an |the )?(?:refund|return|cancellation|address change)\b",
        message,
        re.IGNORECASE,
    ):
        return None
    return topic_signal(message)


def topic_signal(message):
    if re.search(r"\bcancel(?:lation|led|ing)?\b", message, re.IGNORECASE):
        return "cancel_order"
    if re.search(r"\baddress\b", message, re.IGNORECASE):
        return "change_address"
    if re.search(
        r"\b(refund|return|warranty|damaged|broken|human|representative)\b",
        message,
        re.IGNORECASE,
    ):
        return "human_review"
    return None


def current_entity_task(message, history, candidates, topic):
    """Resolve a singular conversational entity, independently of the new question."""
    text = message.lower()
    if re.search(
        r"\b(instead|actually|not that|i meant|other|another|different|earlier|previous|back to|never mind|forget|abandon|stop)\b",
        text,
    ):
        return None
    order_reference = bool(re.search(r"\b(?:that|this|the same) order\b", text))
    case_reference = bool(
        re.search(r"\b(?:that|this|the same) (?:case|ticket)\b", text)
    )
    if re.fullmatch(r"(?:that|this)(?: one)?[.!? ]*", text):
        return None
    pronoun_reference = bool(re.search(r"\b(it|that|this)\b", text))
    if not order_reference and not case_reference and not pronoun_reference:
        return None
    anchor = next(
        (
            turn
            for turn in reversed(history)
            if turn.stop_reason != "task_reference_ambiguous"
        ),
        None,
    )
    if anchor is None or anchor.task_id is None:
        return None
    task = next(
        (
            task
            for task in candidates
            if task.task_id == anchor.task_id and task.status != "abandoned"
        ),
        None,
    )
    if task is None or (topic is not None and topic != task.kind):
        return None
    if not order_reference and not case_reference:
        order_reference = (
            len(anchor.order_ids) == 1 and task.selected_order_ids == anchor.order_ids
        )
        case_reference = len(anchor.case_ids) == 1 and task.case_ids == anchor.case_ids
        if order_reference == case_reference:
            return None
    if order_reference and case_reference:
        return None
    if order_reference:
        # Both the immediately discussed turn and checkpoint must agree on one target.
        if len(anchor.order_ids) != 1 or task.selected_order_ids != anchor.order_ids:
            return None
        explicit = set(re.findall(r"\border-[a-zA-Z0-9-]+\b", message))
        if explicit and explicit != set(anchor.order_ids):
            return None
    if case_reference and (
        len(anchor.case_ids) != 1 or task.case_ids != anchor.case_ids
    ):
        return None
    return task


async def route_message(
    request, history, candidates, judge, on_precheck=None, on_input=None
):
    state = precheck(
        SupportRequest(conversation_id="routing", message=request.message), history
    )
    semantic_candidates = (
        [c for c in candidates if c.status != "completed"]
        + [c for c in candidates if c.status == "completed"]
    )[:8]
    state["tasks"] = [
        {
            **c.model_dump(
                mode="json",
                exclude={
                    "completed_steps",
                    "saved_policy",
                    "evidence_ids",
                    "last_answer",
                    "pending_question",
                },
            ),
            "goal": c.goal[:500],
            "last_answer": c.last_answer[:500],
            "pending_question": (c.pending_question or "")[:500],
        }
        for c in semantic_candidates
    ]
    kind = kind_signal(request.message)
    topic = topic_signal(request.message)
    state["task_kind_signal"] = kind
    state["task_topic_signal"] = topic
    entity_task = current_entity_task(request.message, history, candidates, topic)
    state["resolved_current_entity"] = (
        {
            "task_id": entity_task.task_id,
            "order_ids": entity_task.selected_order_ids,
            "case_ids": entity_task.case_ids,
        }
        if entity_task
        else None
    )
    if on_precheck:
        on_precheck(state)
    if len(json.dumps(state)) > 28000:
        return TaskRoute(route="clarify"), state, "context_limit"
    if request.task_id:
        if not any(c.task_id == request.task_id for c in candidates):
            raise LookupError("Task not found")
        return (
            TaskRoute(route="resume", task_id=request.task_id),
            state,
            "explicit_task",
        )
    if entity_task:
        return (
            TaskRoute(route="resume", task_id=entity_task.task_id),
            state,
            "resolved_current_entity",
        )
    waiting = [c for c in candidates if c.status not in {"completed", "abandoned"}]
    text = request.message.strip().lower()
    correction = bool(
        re.search(r"\b(instead|actually|not that|i meant|other one)\b", text)
    )
    abandonment = bool(
        re.fullmatch(
            r"(?:never mind|nevermind|forget it|stop this request|abandon this request)[.! ]*",
            text,
        )
    )
    recent_task = history[-1].task_id if history else None
    if abandonment and len(waiting) == 1 and recent_task == waiting[0].task_id:
        return (
            TaskRoute(route="abandon", task_id=waiting[0].task_id),
            state,
            "explicit_abandonment",
        )
    reference = bool(
        re.search(r"\b(it|that|those|this|previous|earlier|back to)\b", text)
    )
    if topic and not correction and (kind or reference):
        matching = [c for c in waiting if c.kind == topic]
        explicit_orders = set(re.findall(r"\border-[a-zA-Z0-9-]+\b", request.message))
        matching = [
            c
            for c in matching
            if not explicit_orders
            or not c.selected_order_ids
            or explicit_orders <= set(c.selected_order_ids)
        ]
        if len(matching) == 1:
            return (
                TaskRoute(route="resume", task_id=matching[0].task_id),
                state,
                "unique_topic",
            )
        if not matching and kind:
            return TaskRoute(route="new", task_kind=kind), state, "new_topic"
    short = bool(
        re.fullmatch(
            r"(?:yes|no|okay|ok|that one|please|try again|retry|order-[a-z0-9-]+)[,.! ]*",
            text,
        )
    )
    if (
        (short or is_confirmation_reply(text))
        and len(waiting) == 1
        and recent_task == waiting[0].task_id
    ):
        return (
            TaskRoute(route="resume", task_id=waiting[0].task_id),
            state,
            "reply_to_current_task",
        )
    referential = (
        correction or abandonment or short or is_confirmation_reply(text) or reference
    )
    if not candidates or (not referential and not kind):
        return TaskRoute(route="new", task_kind=kind), state, "standalone_request"
    exhausted = [
        c
        for c in semantic_candidates
        if c.resources.executions >= TASK_LIMITS.executions
        or c.resources.tokens >= TASK_LIMITS.tokens
    ]
    if (
        len(waiting) == 1
        and recent_task == waiting[0].task_id
        and waiting[0] in exhausted
    ):
        return (
            TaskRoute(route="resume", task_id=waiting[0].task_id),
            state,
            "current_task_budget_gate",
        )
    if len(exhausted) == len(semantic_candidates):
        return TaskRoute(route="clarify"), state, "routing_budget_gate"
    if on_input:
        on_input(state)
    try:
        result = await asyncio.wait_for(judge.route_task(state), timeout=15)
    except Exception as exc:
        raise ModelBoundaryFailure(type(exc).__name__, str(exc)[:500], {}, []) from exc
    if result.probability < 0.8:
        result = TaskRoute(
            route="clarify", probability=result.probability, usage=result.usage
        )
    if result.task_id and not any(
        c.task_id == result.task_id for c in semantic_candidates
    ):
        raise ValueError("Routing selected an unavailable task")
    return result, state, "jev_continuation"
