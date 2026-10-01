"""Conversation routing chooses context, never authorization or execution."""

import asyncio
import json
import re

from .contracts import SupportRequest, TaskRoute
from .providers import ModelBoundaryFailure
from .service import is_confirmation_reply, precheck


def kind_signal(message):
    if re.search(r"\b(policy|rules)\b", message, re.IGNORECASE) and not re.search(
        r"\b(want|need|please|submit|create|request)\b", message, re.IGNORECASE
    ):
        return None
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
    state["task_kind_signal"] = kind
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
    if kind and not correction:
        matching = [c for c in waiting if c.kind == kind]
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
        if not matching:
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
        correction
        or abandonment
        or short
        or is_confirmation_reply(text)
        or bool(re.search(r"\b(it|that|those|previous|earlier|back to)\b", text))
    )
    if not candidates or (not referential and not kind):
        return TaskRoute(route="new", task_kind=kind), state, "standalone_request"
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
