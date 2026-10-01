"""Bounded read-only support harness with visible checks around model calls."""

import asyncio
import json
import re
from collections.abc import Callable
from decimal import Decimal

from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from backend.internal_knowledge_action.embedding import EmbeddingProvider

from .contracts import (
    AddressProposal,
    AnswerDraft,
    CancelProposal,
    CaseCategory,
    CaseRequest,
    CompatibilityRequest,
    ConversationTurn,
    EmptyArgs,
    Evidence,
    Intent,
    OrderArgs,
    PolicySearchArgs,
    ProductArgs,
    RecordLookupRequest,
    SupportRequest,
    SupportResponse,
    SupportStep,
    TaskCheckpoint,
)
from .providers import Judge, ModelBoundaryFailure, SupportModel
from .retrieval import IndexUnavailable, PolicyIndex, search
from .store import CustomerStore, MockStore, review_order

MAX_TURNS = 8
MAX_TOOL_CALLS = 6
MAX_CONTEXT_CHARS = 28000
MAX_HISTORY_TURNS = 4
MAX_TOKENS = 20000
THRESHOLD = 0.8
SIGNALS = {
    "order": r"\b(order|shipping|delivery|arrive|tracking)\b",
    "policy": r"\b(policy|return|warranty|refund|cancel)\b",
    "compatibility": r"\b(lens|camera|compatible|mount|fit)\b",
    "action": r"\b(cancel|change|update|process|refund|return|submit)\b",
    "human": r"\b(human|representative|person|agent)\b",
}
EXECUTION = re.compile(
    r"\b(refund(?:ed)?|cancel(?:led|ed)|case|address|return)\b.{0,35}\b(processed|issued|completed|created|approved|updated|guaranteed)\b|\b(?:I|we)\s+(?:have\s+)?(?:refunded|cancelled|canceled|approved|created|updated)\b|\b(?:you(?:'ll| will)|we will)\s+(?:get|receive|issue|process)\s+(?:a |your |the )?refund\b",
    re.IGNORECASE,
)


def is_confirmation_reply(message):
    """Cheap continuation signal; never authority to execute a proposal."""
    return bool(
        re.fullmatch(
            r"(?:(?:yes|ok|okay)[, ]+)?(?:yes|no|ok|okay|confirm|go ahead(?: and (?:do|cancel) it)?|(?:please )?(?:do|cancel) (?:it|that)(?: for me)?|proceed(?: with (?:it|that))?|yes,? cancel please|cancel please)(?: please)?[.! ]*",
            message.strip(),
            re.IGNORECASE,
        )
    )


def precheck(request: SupportRequest, history: list[ConversationTurn]) -> dict:
    message = " ".join(request.message.split())
    if not re.search(r"[a-zA-Z0-9]", message):
        raise ValueError("Message needs readable text")
    recent = [
        turn.model_copy(
            update={"question": turn.question[:500], "answer": turn.answer[:1500]}
        )
        for turn in history[-MAX_HISTORY_TURNS:]
    ]
    return {
        "message": message,
        "signals": [
            key
            for key, pattern in SIGNALS.items()
            if re.search(pattern, message, re.IGNORECASE)
        ],
        "recent_turns": [turn.model_dump(mode="json") for turn in recent],
        "prior_turns_are_evidence": False,
    }


def verify(draft: AnswerDraft, catalog: dict[str, Evidence]) -> tuple[bool, str]:
    for claim in draft.claims:
        if EXECUTION.search(claim.text):
            return False, "action_or_refund_claim"
        if any(key not in catalog for key in claim.evidence_ids):
            return False, "unknown_citation"
        source = " ".join(catalog[key].text for key in claim.evidence_ids)
        numbers = re.findall(r"\b\d+(?:\.\d+)?\b", claim.text)
        source_numbers = {
            Decimal(number) for number in re.findall(r"\b\d+(?:\.\d+)?\b", source)
        }
        if any(Decimal(number) not in source_numbers for number in numbers):
            return False, "unsupported_number"
        for order_id in re.findall(r"\border-[a-zA-Z0-9_-]+", claim.text):
            if order_id not in source:
                return False, "unsupported_order_id"
    return True, "provenance_passed"


def render(draft: AnswerDraft) -> str:
    if draft.format == "bullet_list":
        return "\n".join(f"- {claim.text}" for claim in draft.claims)
    if draft.format == "numbered_list":
        return "\n".join(
            f"{rank}. {claim.text}" for rank, claim in enumerate(draft.claims, 1)
        )
    return "\n\n".join(claim.text for claim in draft.claims)


async def run_support(
    request: SupportRequest,
    store: MockStore,
    customer: CustomerStore,
    model: SupportModel,
    judge: Judge,
    index: PolicyIndex | None,
    embedder: EmbeddingProvider,
    run_id: str,
    history: list[ConversationTurn] | None = None,
    on_step: Callable[[SupportStep], None] | None = None,
    operations_enabled: bool = False,
    case_lookup=None,
    pending_ids: list[str] | None = None,
    task_checkpoint: TaskCheckpoint | None = None,
    task_resumed: bool = False,
    initial_usage: dict | None = None,
) -> SupportResponse:
    steps, catalog, usage = [], {}, {}
    usage.update(initial_usage or {})
    tool_count = 0
    repairs = 0
    deadline = asyncio.get_running_loop().time() + 120

    async def bounded(call, seconds):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            call.close()
            raise TimeoutError("Support run deadline reached")
        return await asyncio.wait_for(call, timeout=min(seconds, remaining))

    def step(stage, **details):
        item = SupportStep(
            sequence=len(steps) + 1,
            stage=stage,
            details=to_jsonable_python(details),
        )
        steps.append(item)
        if on_step:
            on_step(item)

    def finish(disposition, answer, reason, evidence_ids=(), operation=None):
        step(
            "stop",
            disposition=disposition,
            reason=reason,
            private_reasoning="unavailable",
        )
        return SupportResponse(
            run_id=run_id,
            conversation_id=request.conversation_id,
            disposition=disposition,
            answer=answer,
            stop_reason=reason,
            approved_operation=operation,
            evidence=tuple(catalog[key] for key in dict.fromkeys(evidence_ids)),
            steps=tuple(steps),
            usage=usage,
            embedding_model=index.embedding_model if index else None,
            fixture_version=store.fixture.version,
        )

    def add(kind, source_id, locator, text):
        key = f"S{len(catalog) + 1}"
        item = Evidence(
            evidence_id=key, kind=kind, source_id=source_id, locator=locator, text=text
        )
        catalog[key] = item
        return item.model_dump(mode="json")

    def order_facts(order):
        facts = order.model_dump(mode="json", exclude={"address", "customer_id"})
        for line in facts["lines"]:
            product = store.product(line["product_id"])
            if product is None:
                raise ValueError("Unknown fixture product")
            line["product_name"] = product.name
            line["product_kind"] = product.kind
            line["unit_price_usd"] = str(Decimal(line["unit_price_cents"]) / 100)
        facts["read_only_review"] = review_order(order, store).model_dump(mode="json")
        facts["scenario_date"] = str(store.fixture.scenario_date)
        facts["policy_rule_inputs"] = store.fixture.rules.model_dump(mode="json")
        return facts

    try:
        state = precheck(request, history or [])
        if task_checkpoint:
            state["task_checkpoint"] = task_checkpoint.model_dump(mode="json")
            state["checkpoint_is_current_evidence"] = False
        recent_text = json.dumps(state["recent_turns"])
        state["references"] = {
            "owned_order_ids": [
                o.order_id for o in customer.orders() if o.order_id in recent_text
            ],
            "catalog_product_ids": [
                p.product_id
                for p in store.fixture.products
                if p.product_id in recent_text
            ],
        }
        if task_checkpoint:
            state["references"]["owned_order_ids"] = [
                key
                for key in task_checkpoint.selected_order_ids
                if customer.order(key).order is not None
            ]
        step(
            "request_check",
            **state,
            scope="server-bound customer; read-only tools",
            prompt_version="support-v1",
            fixture_version=store.fixture.version,
        )
        if task_checkpoint:
            step(
                "task_resumed" if task_resumed else "task_created",
                checkpoint=task_checkpoint.model_dump(mode="json"),
                current_state_refresh_required=True,
            )
            if task_checkpoint.status == "awaiting_approval" and is_confirmation_reply(
                state["message"]
            ):
                step(
                    "confirmation_route_check",
                    pending_proposal_ids=pending_ids or [],
                    task_id=task_checkpoint.task_id,
                )
                return finish(
                    "clarification",
                    "Please confirm or reject the existing request using its confirmation card.",
                    "explicit_confirmation_required",
                )
        if re.fullmatch(
            r"(?:what are my orders|(?:show|list)(?: me)? my orders|my orders)[?.!]*",
            state["message"].lower(),
        ):
            step("deterministic_route", route="owned_order_list", model_required=False)
            step("tool_request", name="order_list", arguments={})
            orders = customer.orders()
            evidence_ids = []
            lines = [
                "| Ordered | Items | Payment | Delivery |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for order in orders:
                facts = order.model_dump(
                    mode="json", exclude={"address", "customer_id"}
                )
                record = add(
                    "order",
                    order.order_id,
                    "current_owned_order_snapshot",
                    json.dumps(facts),
                )
                evidence_ids.append(record["evidence_id"])
                products = ", ".join(
                    f"{line.quantity} × {next((p.name for p in store.fixture.products if p.product_id == line.product_id), line.product_id)}"
                    for line in order.lines
                )
                lines.append(
                    f"| {order.placed_on} | {products.replace(chr(124), chr(92) + chr(124))} | {order.state.value.capitalize()} | {order.fulfillment.value.replace('_', ' ').capitalize()} |"
                )
            step(
                "tool_result",
                name="order_list",
                observations=[
                    catalog[key].model_dump(mode="json") for key in evidence_ids
                ],
            )
            step(
                "deterministic_answer_check",
                source="owned current order records",
                count=len(orders),
                passed=True,
            )
            return finish(
                "answered",
                "Here are your orders:\n\n" + "\n".join(lines)
                if orders
                else "You don’t have any orders yet.",
                "owned_order_list",
                evidence_ids,
            )
        # A bounded, validated snapshot is supplied before every Jev/model call.
        if len(json.dumps(state)) > MAX_CONTEXT_CHARS:
            return finish(
                "clarification",
                "Please ask a shorter question with fewer details.",
                "context_limit",
            )
        if (
            operations_enabled
            and pending_ids
            and re.fullmatch(
                r"(yes|ok|okay|confirm|go ahead)[.! ]*", state["message"], re.IGNORECASE
            )
        ):
            step("confirmation_route_check", pending_proposal_ids=pending_ids)
            return finish(
                "clarification",
                "Please confirm or reject the specific pending proposal using its confirmation action.",
                "explicit_confirmation_required",
            )
        step("intent_input", state=state, model=judge.model_id)
        judgment = await bounded(judge.classify(state), 15)
        usage["intent"] = judgment.usage
        if (
            task_checkpoint
            and task_checkpoint.status == "awaiting_approval"
            and judgment.intent == Intent.ACTION
        ):
            step(
                "confirmation_route_check",
                pending_proposal_ids=pending_ids or [],
                task_id=task_checkpoint.task_id,
            )
            return finish(
                "clarification",
                "Please confirm or reject the existing request using its confirmation card.",
                "explicit_confirmation_required",
            )
        step(
            "intent_judgment",
            judgment=judgment.model_dump(mode="json"),
            threshold=THRESHOLD,
        )
        if judgment.probability < THRESHOLD:
            if judgment.intent not in (Intent.INFORMATION, Intent.ACTION):
                return finish(
                    "clarification",
                    "Could you clarify what you need help with?",
                    "intent_uncertain",
                )
            # Uncertainty about explanation versus execution must not block
            # authorized reads. It must not authorize a proposal or a write.
            operations_enabled = False
            step(
                "intent_route_check",
                route="read_only",
                reason="uncertain_information_or_action",
                classified_intent=judgment.intent.value,
                operation_proposals_enabled=False,
            )
            judgment = judgment.model_copy(update={"intent": Intent.INFORMATION})
        state["pending_proposal_ids"] = pending_ids or []
        state["case_ids"] = list(
            dict.fromkeys(key for turn in (history or []) for key in turn.case_ids)
        )
        if operations_enabled and judgment.intent == Intent.HUMAN:
            operation = CaseRequest(
                kind="create_case",
                category=CaseCategory.GENERAL,
                customer_statement=state["message"][:1000],
            )
            step(
                "case_request_check", category="general_support", application_owned=True
            )
            return finish(
                "handoff_needed",
                "Saving your request for human review.",
                "case_request_validated",
                operation=operation,
            )
        if judgment.intent == Intent.UNSUPPORTED:
            return finish(
                "clarification",
                "I can help with camera equipment, orders, and store policies. What would you like to know?",
                "unsupported_request",
            )
        if not operations_enabled and judgment.intent != Intent.INFORMATION:
            return finish(
                "handoff_needed",
                "This request needs human support review. No action has been performed and no case has been created yet.",
                f"{judgment.intent.value}_handoff",
            )
        state["tools"] = {
            "policy_search": {"query": "bounded text"},
            "order_list": {},
            "order_detail": {"order_id": "owned order ID"},
            "catalog_list": {},
            "product_detail": {"product_id": "catalog ID"},
            "compatibility": {"body_id": "catalog ID", "lens_id": "catalog ID"},
        }
        if operations_enabled:
            state["tools"]["case_detail"] = {
                "record_id": "case ID from this conversation"
            }
        state["operation_proposals_enabled"] = operations_enabled
        state["intent"] = judgment.intent.value
        state["observations"] = []
        if (
            task_resumed
            and task_checkpoint
            and task_checkpoint.kind in {"cancel_order", "change_address"}
            and len(state["references"]["owned_order_ids"]) == 1
        ):
            order_id = state["references"]["owned_order_ids"][0]
            current = customer.order(order_id).order
            if current is not None:
                step(
                    "tool_request",
                    name="order_detail",
                    arguments={"order_id": order_id},
                    application_owned=True,
                )
                facts = order_facts(current)
                observation = add(
                    "order", order_id, "current_owned_order_snapshot", json.dumps(facts)
                )
                step(
                    "eligibility_check",
                    order_id=order_id,
                    rules=facts["policy_rule_inputs"],
                    result=facts["read_only_review"],
                    execution_authorized=False,
                )
                step("tool_result", name="order_detail", observations=[observation])
                state["observations"].append(
                    {
                        "tool": {
                            "name": "order_detail",
                            "arguments": {"order_id": order_id},
                        },
                        "results": [observation],
                    }
                )
                tool_count += 1
                state["tools"].pop("order_detail", None)
                state["required_evidence"] = (
                    "Current selected order has already been refreshed. Retrieve applicable policy next if needed; reuse this order evidence."
                )
                step(
                    "completed_read_check",
                    source="selected_task_order",
                    removed_tools=["order_detail"],
                    reason="current_snapshot_already_available",
                )
        for turn in range(MAX_TURNS):
            tokens = sum(
                int(v.get("input_tokens", 0)) + int(v.get("output_tokens", 0))
                for v in usage.values()
            )
            if tokens >= MAX_TOKENS or len(json.dumps(state)) > MAX_CONTEXT_CHARS:
                return finish(
                    "handoff_needed",
                    "The support check reached its limit. Human review is needed.",
                    "context_or_token_budget",
                )
            state["remaining_token_budget"] = MAX_TOKENS - tokens
            step(
                "model_precheck",
                turn=turn + 1,
                tool_calls=tool_count,
                tokens=tokens,
                context_chars=len(json.dumps(state)),
            )
            step("model_input", model=model.model_id, state=state.copy())
            output, counts = await bounded(model.turn(state, run_id), 40)
            usage[f"model_{turn + 1}"] = counts
            step("model_output", output=output.model_dump(mode="json"), usage=counts)
            if state.get("final_decision_only") and output.tool is not None:
                return finish(
                    "clarification",
                    "What specific detail would you like help with?",
                    "invalid_final_decision",
                )
            if output.proposal is not None:
                operation = output.proposal
                problem = None
                source_text = " ".join(
                    [state["message"], *[t.question for t in (history or [])[-4:]]]
                ).lower()
                if not operations_enabled or judgment.intent != Intent.ACTION:
                    problem = "action_not_requested"
                elif any(key not in catalog for key in operation.evidence_ids):
                    problem = "unknown_operation_citation"
                elif (
                    operation.order_id
                    and customer.order(operation.order_id).order is None
                ):
                    problem = "order_not_found"
                elif operation.order_id and not any(
                    catalog[key].kind == "order"
                    and catalog[key].source_id == operation.order_id
                    for key in operation.evidence_ids
                ):
                    problem = "missing_order_evidence"
                elif isinstance(
                    operation, (CancelProposal, AddressProposal)
                ) and not any(
                    catalog[key].kind == "policy" for key in operation.evidence_ids
                ):
                    problem = "missing_policy_evidence"
                elif (
                    isinstance(operation, CaseRequest)
                    and operation.customer_statement.lower() not in source_text
                ):
                    problem = "invented_customer_statement"
                elif isinstance(operation, AddressProposal) and any(
                    value.lower() not in source_text
                    for value in (
                        operation.address.line1,
                        operation.address.city,
                        operation.address.postal_code,
                    )
                ):
                    problem = "invented_address"
                step(
                    "proposal_check",
                    passed=problem is None,
                    reason=problem,
                    proposal=operation.model_dump(mode="json"),
                )
                if problem:
                    return finish(
                        "clarification",
                        "Please provide the owned order and the complete details of the request.",
                        problem,
                    )
                if isinstance(operation, (CancelProposal, AddressProposal)):
                    current_order = customer.order(operation.order_id).order
                    assert current_order is not None
                    current_review = review_order(current_order, store)
                    step(
                        "proposal_state_check",
                        order_id=operation.order_id,
                        result=current_review.model_dump(mode="json"),
                        rules=store.fixture.rules.model_dump(mode="json"),
                        execution_authorized=False,
                    )
                ground_state = {
                    "proposal": operation.model_dump(mode="json"),
                    "user_request": state["message"],
                    "recent_questions": [t.question for t in (history or [])[-4:]],
                    "verified_observations": [
                        catalog[key].model_dump(mode="json")
                        for key in operation.evidence_ids
                    ],
                    "customer_statement_is_unverified": True,
                }
                tokens = sum(
                    int(v.get("input_tokens", 0)) + int(v.get("output_tokens", 0))
                    for v in usage.values()
                )
                if (
                    len(json.dumps(ground_state)) > MAX_CONTEXT_CHARS
                    or tokens >= MAX_TOKENS
                ):
                    return finish(
                        "handoff_needed",
                        "The proposal needs further review.",
                        "proposal_budget",
                    )
                step(
                    "proposal_grounding_input", state=ground_state, model=judge.model_id
                )
                grounding = await bounded(judge.ground(ground_state), 15)
                usage["proposal_grounding"] = grounding.usage
                step(
                    "proposal_grounding_check",
                    judgment=grounding.model_dump(mode="json"),
                    passed=grounding.probability >= THRESHOLD,
                    threshold=THRESHOLD,
                )
                if grounding.probability < THRESHOLD:
                    return finish(
                        "clarification",
                        "Could you clarify the order and what you want us to do?",
                        "proposal_grounding_rejected",
                    )
                return finish(
                    "handoff_needed",
                    "The checked proposal is ready to save.",
                    "proposal_validated",
                    operation.evidence_ids,
                    operation,
                )
            if output.clarification:
                safe = (
                    output.clarification.endswith("?")
                    and not EXECUTION.search(output.clarification)
                    and not re.search(
                        r"\bcase[- _]\d+", output.clarification, re.IGNORECASE
                    )
                )
                step("clarification_check", passed=safe)
                if not safe:
                    return finish(
                        "clarification",
                        "Which order, product, or policy would you like help with?",
                        "unsafe_clarification",
                    )
                return finish(
                    "clarification", output.clarification, "missing_reference"
                )
            if output.answer:
                passed, reason = verify(output.answer, catalog)
                step("citation_check", passed=passed, reason=reason)
                if passed:
                    ground_state = {
                        "claims": [
                            {
                                "text": c.text,
                                "cited_observations": [
                                    catalog[key].model_dump(mode="json")
                                    for key in c.evidence_ids
                                ],
                            }
                            for c in output.answer.claims
                        ]
                    }
                    if len(json.dumps(ground_state)) > MAX_CONTEXT_CHARS:
                        return finish(
                            "handoff_needed",
                            "The answer needs further support review.",
                            "grounding_context_limit",
                        )
                    reported_tokens = sum(
                        int(v.get("input_tokens", 0)) + int(v.get("output_tokens", 0))
                        for v in usage.values()
                    )
                    if reported_tokens >= MAX_TOKENS:
                        return finish(
                            "handoff_needed",
                            "The support check reached its token limit. Human review is needed.",
                            "token_budget",
                        )
                    step(
                        "grounding_precheck",
                        tokens=reported_tokens,
                        context_chars=len(json.dumps(ground_state)),
                        scope="only deterministically checked cited evidence",
                    )
                    step("grounding_input", state=ground_state, model=judge.model_id)
                    grounding = await bounded(judge.ground(ground_state), 15)
                    usage[f"grounding_{repairs}"] = grounding.usage
                    passed = grounding.probability >= THRESHOLD
                    step(
                        "grounding_check",
                        judgment=grounding.model_dump(mode="json"),
                        passed=passed,
                        threshold=THRESHOLD,
                    )
                    reason = "grounding_rejected" if not passed else "verified"
                if passed:
                    return finish(
                        "answered",
                        render(output.answer),
                        "verified",
                        [key for c in output.answer.claims for key in c.evidence_ids],
                    )
                if repairs == 1:
                    return finish(
                        "handoff_needed",
                        "I could not verify an answer from the available information. Human support review is needed.",
                        reason,
                    )
                repairs += 1
                state["repair"] = {
                    "reason": reason,
                    "instruction": "Repair once using only current cited observations, or ask a clarification.",
                }
                step("repair", reason=reason, attempt=repairs)
                continue
            tool_count += 1
            if tool_count > MAX_TOOL_CALLS:
                return finish(
                    "handoff_needed",
                    "The lookup reached its limit. Human support review is needed.",
                    "tool_budget",
                )
            call = output.tool
            if call is None:
                raise ValueError("Model turn has no tool")
            if any(
                previous["tool"] == call.model_dump(mode="json")
                for previous in state["observations"]
            ):
                step(
                    "duplicate_tool_check",
                    name=call.name,
                    arguments=call.arguments,
                    passed=False,
                )
                if (
                    operations_enabled
                    and judgment.intent == Intent.ACTION
                    and any(item.kind == "order" for item in catalog.values())
                    and not any(item.kind == "policy" for item in catalog.values())
                ):
                    state["tools"] = {"policy_search": {"query": "bounded text"}}
                    state["required_evidence"] = (
                        "Retrieve applicable policy before proposing an operation; reuse the current order observation."
                    )
                    step(
                        "evidence_completion_check",
                        missing="policy",
                        route="policy_search",
                    )
                    continue
                state["final_decision_only"] = True
                state["tools"] = {}
                step("source_selection_closed", reason="repeated_tool_call")
                continue
            if call.name not in state["tools"]:
                step("tool_availability_check", name=call.name, passed=False)
                return finish(
                    "clarification",
                    "I couldn’t complete that lookup. Please clarify what you would like to check.",
                    "unavailable_tool",
                )
            step("tool_request", name=call.name, arguments=call.arguments)
            try:
                observations = []
                if call.name == "policy_search":
                    args = PolicySearchArgs.model_validate(call.arguments)
                    if index is None:
                        raise IndexUnavailable(
                            "Policy index unavailable; explicit ingestion required"
                        )
                    passages, ranks = await bounded(
                        asyncio.to_thread(search, store, index, embedder, args.query),
                        25,
                    )
                    for p in passages:
                        policy = next(
                            x
                            for x in store.fixture.policies
                            if x.policy_id == p.policy_id and x.locator == p.locator
                        )
                        observations.append(
                            add(
                                "policy",
                                p.policy_id,
                                f"{policy.revision}:{p.locator}",
                                p.text,
                            )
                        )
                    step("policy_retrieval", **ranks)
                elif call.name == "order_list":
                    EmptyArgs.model_validate(call.arguments)
                    observations.extend(
                        add(
                            "order",
                            order.order_id,
                            "current_owned_order_snapshot",
                            json.dumps(order_facts(order)),
                        )
                        for order in customer.orders()
                    )
                elif call.name == "order_detail":
                    args = OrderArgs.model_validate(call.arguments)
                    result = customer.order(args.order_id)
                    if result.order:
                        facts = order_facts(result.order)
                        review = review_order(result.order, store)
                        step(
                            "eligibility_check",
                            order_id=args.order_id,
                            rules=store.fixture.rules.model_dump(mode="json"),
                            result=review.model_dump(mode="json"),
                            execution_authorized=False,
                        )
                        observations.append(
                            add(
                                "order",
                                args.order_id,
                                "state,fulfillment,dates,lines; rules:fixture-v2",
                                json.dumps(facts, sort_keys=True),
                            )
                        )
                    else:
                        observations.append({"status": "not_found"})
                elif call.name == "catalog_list":
                    EmptyArgs.model_validate(call.arguments)
                    observations.append(
                        {
                            "products": [
                                {
                                    "product_id": p.product_id,
                                    "name": p.name,
                                    "kind": p.kind,
                                }
                                for p in store.fixture.products
                            ]
                        }
                    )
                elif call.name == "product_detail":
                    args = ProductArgs.model_validate(call.arguments)
                    product = store.product(args.product_id)
                    observations.append(
                        add(
                            "catalog",
                            args.product_id,
                            "name,kind,mount,provenance",
                            product.model_dump_json(),
                        )
                        if product
                        else {"status": "not_found"}
                    )
                elif call.name == "case_detail":
                    args = RecordLookupRequest.model_validate(call.arguments)
                    case = (
                        case_lookup(args.record_id)
                        if operations_enabled and case_lookup
                        else None
                    )
                    observations.append(
                        add(
                            "case",
                            args.record_id,
                            "saved_pending_review",
                            case.model_dump_json(),
                        )
                        if case
                        else {"status": "not_found"}
                    )
                else:
                    args = CompatibilityRequest.model_validate(call.arguments)
                    pair = store.compatibility(args.body_id, args.lens_id)
                    observations.append(
                        add(
                            "compatibility",
                            f"{args.body_id}/{args.lens_id}",
                            "exact_pair",
                            pair.model_dump_json(),
                        )
                    )
                step("tool_result", name=call.name, observations=observations)
                state["observations"].append(
                    {"tool": call.model_dump(mode="json"), "results": observations}
                )
                if call.name == "order_list":
                    # The list contains complete current snapshots, not summaries.
                    # A detail read cannot add facts for any of these owned orders.
                    state["tools"].pop("order_list", None)
                    state["tools"].pop("order_detail", None)
                    step(
                        "completed_read_check",
                        source="owned_order_snapshots",
                        removed_tools=["order_list", "order_detail"],
                        reason="complete_snapshots_already_available",
                    )
                # A repeated result adds no evidence, even if the query was reworded.
                previous_sources = {
                    (
                        item.get("kind"),
                        item.get("source_id"),
                        item.get("locator"),
                        item.get("text"),
                    )
                    for entry in state["observations"][:-1]
                    for item in entry["results"]
                    if "evidence_id" in item
                }
                new_sources = {
                    (
                        item.get("kind"),
                        item.get("source_id"),
                        item.get("locator"),
                        item.get("text"),
                    )
                    for item in observations
                    if "evidence_id" in item
                }
                if (
                    (new_sources and new_sources <= previous_sources)
                    or call.name in {"compatibility", "case_detail"}
                    or tool_count >= MAX_TOOL_CALLS
                    or (
                        call.name in {"order_detail", "order_list", "policy_search"}
                        and any(item.kind == "order" for item in catalog.values())
                        and any(item.kind == "policy" for item in catalog.values())
                    )
                ):
                    state["final_decision_only"] = True
                    state["tools"] = {}
                    step(
                        "source_selection_closed",
                        reason="no_new_evidence"
                        if new_sources <= previous_sources
                        else "bounded_context_ready",
                    )
            except IndexUnavailable as exc:
                step("tool_failure", name=call.name, reason=str(exc))
                return finish(
                    "handoff_needed",
                    "Policy search is unavailable. Human support review is needed.",
                    "policy_index_unavailable",
                )
            except (ValidationError, ValueError) as exc:
                step("tool_failure", name=call.name, reason=type(exc).__name__)
                return finish(
                    "handoff_needed",
                    "The requested lookup could not be validated. Human support review is needed.",
                    "invalid_tool_arguments",
                )
        return finish(
            "handoff_needed",
            "The support check reached its turn limit. Human review is needed.",
            "turn_budget",
        )
    except Exception as exc:  # noqa: BLE001 - save a terminal provider failure
        if isinstance(exc, ModelBoundaryFailure):
            usage["failed_model"] = exc.usage
            step(
                "failure",
                error_type=exc.error_type,
                error_message=str(exc),
                validation_diagnostics=exc.diagnostics,
                usage=exc.usage,
            )
        else:
            step(
                "failure", error_type=type(exc).__name__, error_message=str(exc)[:1500]
            )
        return finish(
            "handoff_needed",
            "I couldn’t complete that answer. Please try again or ask to contact our support team.",
            "provider_or_validation_failure",
        )
