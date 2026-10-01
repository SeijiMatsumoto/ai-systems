"""Bounded read-only support harness with visible checks around model calls."""

import asyncio
import json
import re
from collections.abc import Callable
from decimal import Decimal

from pydantic import ValidationError

from backend.internal_knowledge_action.embedding import EmbeddingProvider

from .contracts import (
    AnswerDraft,
    CompatibilityRequest,
    ConversationTurn,
    EmptyArgs,
    Evidence,
    Intent,
    OrderArgs,
    PolicySearchArgs,
    ProductArgs,
    SupportRequest,
    SupportResponse,
    SupportStep,
)
from .providers import Judge, SupportModel
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
        "context_is_evidence": False,
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
) -> SupportResponse:
    steps, catalog, usage = [], {}, {}
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
            details=json.loads(json.dumps(details)),
        )
        steps.append(item)
        if on_step:
            on_step(item)

    def finish(disposition, answer, reason, evidence_ids=()):
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

    try:
        state = precheck(request, history or [])
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
        step(
            "request_check",
            **state,
            scope="server-bound customer; read-only tools",
            prompt_version="support-v1",
            fixture_version=store.fixture.version,
        )
        # A bounded, validated snapshot is supplied before every Jev/model call.
        if len(json.dumps(state)) > MAX_CONTEXT_CHARS:
            return finish(
                "clarification",
                "Please ask a shorter question with fewer details.",
                "context_limit",
            )
        step("intent_input", state=state, model=judge.model_id)
        judgment = await bounded(judge.classify(state), 15)
        usage["intent"] = judgment.usage
        step(
            "intent_judgment",
            judgment=judgment.model_dump(mode="json"),
            threshold=THRESHOLD,
        )
        if judgment.probability < THRESHOLD:
            return finish(
                "clarification",
                "Could you clarify what you need help with?",
                "intent_uncertain",
            )
        if judgment.intent != Intent.INFORMATION:
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
        state["observations"] = []
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
                    # Listing disambiguates IDs; it cannot support current order-state claims.
                    listing = [
                        {
                            "order_id": o.order_id,
                            "product_ids": [line.product_id for line in o.lines],
                        }
                        for o in customer.orders()
                    ]
                    observations.append(
                        {
                            "owned_orders": listing,
                            "instruction": "Use order_detail before describing order state",
                        }
                    )
                elif call.name == "order_detail":
                    args = OrderArgs.model_validate(call.arguments)
                    result = customer.order(args.order_id)
                    if result.order:
                        facts = result.order.model_dump(
                            mode="json", exclude={"address", "customer_id"}
                        )
                        for line in facts["lines"]:
                            line["unit_price_usd"] = str(
                                Decimal(line["unit_price_cents"]) / 100
                            )
                        facts["scenario_date"] = str(store.fixture.scenario_date)
                        review = review_order(result.order, store)
                        facts["read_only_review"] = review.model_dump(mode="json")
                        facts["policy_rule_inputs"] = store.fixture.rules.model_dump(
                            mode="json"
                        )
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
        step("failure", error_type=type(exc).__name__)
        return finish(
            "handoff_needed",
            "Support could not complete this check. Human review is needed.",
            "provider_or_validation_failure",
        )
