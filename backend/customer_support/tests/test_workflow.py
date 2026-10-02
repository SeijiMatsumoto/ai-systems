"""Read-only support component and multi-tool workflow evaluations; all providers fake."""

import copy
import json
import tempfile
import unittest
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_ai.usage import RunUsage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.customer_support import api
from backend.customer_support.contracts import (
    AnswerDraft,
    Claim,
    ConversationTurn,
    Intent,
    IntentJudgment,
    Judgment,
    ModelTurn,
    Order,
    PolicyIndex,
    SupportRequest,
    TaskRoute,
    ToolCall,
)
from backend.customer_support.providers import LiveJevJudge, LiveSupportModel
from backend.customer_support.repository import ConversationBusy, SupportRepository
from backend.customer_support.retrieval import (
    IndexUnavailable,
    ingest,
    load_index,
    search,
)
from backend.customer_support.service import run_support
from backend.customer_support.store import CustomerStore, MockStore
from backend.db.schemas import (
    Base,
    LlmRun,
    SupportCase,
    SupportConversation,
    SupportDemoSession,
    SupportOrder,
    SupportOutput,
    SupportProposal,
    SupportReceipt,
    SupportTask,
)
from backend.internal_knowledge_action.embedding import MockEmbeddingProvider


class FakeJudge:
    model_id = "fake-jev"

    def __init__(self, intent=Intent.INFORMATION, probability=0.95, grounding=0.95):
        self.intent = intent
        self.probability = probability
        self.grounding = grounding
        self.calls = []
        self.route_decision: TaskRoute | None = None

    async def route_task(self, state):
        self.calls.append(("continuation", copy.deepcopy(state)))
        if self.route_decision:
            return self.route_decision
        if len(state["tasks"]) == 1:
            return TaskRoute(
                route="resume",
                task_id=state["tasks"][0]["task_id"],
                usage={"input_tokens": 40, "output_tokens": 2},
            )
        return TaskRoute(
            route="clarify",
            probability=0.5,
            usage={"input_tokens": 40, "output_tokens": 2},
        )

    async def classify(self, state):
        self.calls.append(("intent", copy.deepcopy(state)))
        return IntentJudgment(
            intent=self.intent,
            probability=self.probability,
            model=self.model_id,
            usage={"input_tokens": 40, "output_tokens": 2},
        )

    async def ground(self, state):
        self.calls.append(("ground", copy.deepcopy(state)))
        return Judgment(
            probability=self.grounding,
            model=self.model_id,
            usage={"input_tokens": 70, "output_tokens": 2},
        )


ScriptItem = ModelTurn | Exception | Callable[[dict[str, Any]], ModelTurn]


def require_order(customer: CustomerStore, order_id: str) -> Order:
    order = customer.order(order_id).order
    assert order is not None, f"Missing test order: {order_id}"
    return order


class ScriptModel:
    model_id = "fake-support"

    def __init__(self, script: Iterable[ScriptItem]):
        self.script: list[ScriptItem] = list(script)
        self.calls: list[dict[str, Any]] = []

    async def turn(
        self, state: dict[str, Any], run_id: str
    ) -> tuple[ModelTurn, dict[str, int]]:
        self.calls.append(copy.deepcopy(state))
        next_turn = self.script.pop(0)
        if isinstance(next_turn, Exception):
            raise next_turn
        if callable(next_turn):
            next_turn = next_turn(state)
        return next_turn, {"requests": 1, "input_tokens": 100, "output_tokens": 20}


def tool(name, **arguments):
    return ModelTurn(
        decision="Look up relevant facts", tool=ToolCall(name=name, arguments=arguments)
    )


def answer(text="Your order is paid and unfulfilled.", ids=("S1",)):
    return ModelTurn(
        decision="Answer from current evidence",
        answer=AnswerDraft(claims=(Claim(text=text, evidence_ids=ids),)),
    )


def fake_agent_run(turn, usage):
    from backend.customer_support.contracts import DecisionEnvelope

    kind = next(
        key
        for key in ("tool", "answer", "clarification", "proposal")
        if getattr(turn, key) is not None
    )
    envelope = DecisionEnvelope.model_validate(
        {"action": {"kind": kind, "decision": turn.decision, kind: getattr(turn, kind)}}
    )

    class Run:
        result = SimpleNamespace(output=envelope)

        def __init__(self):
            self.usage = usage

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        def all_messages(self):
            return []

    @asynccontextmanager
    async def iterate(*args, **kwargs):
        yield Run()

    return Mock(side_effect=iterate)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = MockStore.load()
        self.embedder = MockEmbeddingProvider()
        self.index = ingest(self.store, self.embedder)

    async def run_case(
        self,
        model,
        judge=None,
        question="Where is order-1001?",
        index=True,
        history=None,
        operations_enabled=False,
    ):
        return await run_support(
            SupportRequest(conversation_id="chat-1", message=question),
            self.store,
            self.store.sign_in("customer-alex"),
            model,
            judge or FakeJudge(),
            self.index if index else None,
            self.embedder,
            str(uuid4()),
            history,
            operations_enabled=operations_enabled,
        )

    async def test_simple_order_list_skips_models_and_returns_all_owned_orders(self):
        model = ScriptModel([])
        judge = FakeJudge()
        result = await self.run_case(model, judge, question="What are my orders?")
        self.assertEqual(result.disposition, "answered")
        self.assertEqual(result.stop_reason, "owned_order_list")
        self.assertIn("| Ordered | Items | Payment | Delivery |", result.answer)
        self.assertEqual(len(result.evidence), 5)
        self.assertEqual(model.calls, [])
        self.assertEqual(judge.calls, [])
        self.assertNotIn("order-2001", result.answer)

    async def test_order_listing_with_provider_decimal_cost(self):
        from decimal import Decimal

        class CostModel(ScriptModel):
            async def turn(self, state, run_id):
                output, usage = await super().turn(state, run_id)
                return output, {
                    **usage,
                    "cost": Decimal("0.0003452"),
                    "details": {"reasoning_tokens": 51},
                }

        def list_answer(state):
            facts = [
                item
                for observation in state["observations"]
                for item in observation["results"]
                if "evidence_id" in item
            ]
            return answer(
                "Your orders are order-1001, order-1002, order-1003, order-1004, and order-1005.",
                tuple(item["evidence_id"] for item in facts[-5:]),
            )

        result = await self.run_case(
            CostModel(
                [
                    tool("order_list"),
                    list_answer,
                ]
            ),
            question="Summarize the details of all my orders.",
        )
        self.assertEqual(result.disposition, "answered")
        self.assertEqual(
            next(step for step in result.steps if step.stage == "model_output").details[
                "usage"
            ]["cost"],
            "0.0003452",
        )
        self.assertNotIn("failure", [step.stage for step in result.steps])

    async def test_noncompliant_provider_cannot_execute_completed_order_read(self):
        result = await self.run_case(
            ScriptModel(
                [tool("order_list"), tool("order_detail", order_id="order-1001")]
            ),
            question="Summarize the details of my orders.",
        )
        self.assertEqual(result.stop_reason, "unavailable_tool")
        self.assertEqual(
            [s.details["name"] for s in result.steps if s.stage == "tool_request"],
            ["order_list"],
        )

    async def test_multi_tool_policy_and_order(self):
        def draft(state):
            observations = [
                item
                for turn in state["observations"]
                for item in turn["results"]
                if "evidence_id" in item
            ]
            policy = next(x for x in observations if x["source_id"] == "returns")
            order = next(x for x in observations if x["kind"] == "order")
            return answer(
                "The order was delivered on 2026-09-15. Return review is available within 30 calendar days after delivery.",
                (policy["evidence_id"], order["evidence_id"]),
            )

        model = ScriptModel(
            [
                tool("policy_search", query="return refund window after delivery"),
                tool("order_detail", order_id="order-1004"),
                draft,
            ]
        )
        result = await self.run_case(model)
        self.assertEqual(result.disposition, "answered")
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(result.usage["model_3"]["output_tokens"], 20)
        stages = [s.stage for s in result.steps]
        self.assertLess(stages.index("request_check"), stages.index("intent_input"))
        self.assertLess(stages.index("citation_check"), stages.index("grounding_input"))
        self.assertEqual(
            [s.sequence for s in result.steps], list(range(1, len(result.steps) + 1))
        )
        first_input = next(s for s in result.steps if s.stage == "model_input")
        self.assertEqual(first_input.details["state"]["observations"], [])

    async def test_prior_context_not_authoritative_and_fresh_read(self):
        history = [
            ConversationTurn(question="Check order-1001", answer="It has shipped.")
        ]
        model = ScriptModel([tool("order_detail", order_id="order-1001"), answer()])
        result = await self.run_case(
            model, question="What about that order now?", history=history
        )
        self.assertEqual(result.disposition, "answered")
        self.assertEqual(model.calls[0]["recent_turns"][0]["answer"], "It has shipped.")
        self.assertIn('"fulfillment": "unfulfilled"', result.evidence[0].text)

    async def test_cross_customer_cannot_be_cited(self):
        result = await self.run_case(
            ScriptModel(
                [tool("order_detail", order_id="order-2001"), answer(), answer()]
            )
        )
        self.assertEqual(result.stop_reason, "unknown_citation")
        self.assertEqual(result.evidence, ())

    async def test_identity_argument_rejected(self):
        result = await self.run_case(
            ScriptModel(
                [
                    tool(
                        "order_detail",
                        order_id="order-1001",
                        customer_id="customer-sam",
                    )
                ]
            )
        )
        self.assertEqual(result.stop_reason, "invalid_tool_arguments")

    async def test_actions_human_and_uncertain(self):
        for intent in (Intent.ACTION, Intent.HUMAN, Intent.UNSUPPORTED):
            model = ScriptModel([])
            result = await self.run_case(
                model, FakeJudge(intent=intent), question="Refund this order"
            )
            self.assertEqual(
                result.disposition,
                "clarification" if intent == Intent.UNSUPPORTED else "handoff_needed",
            )
            if intent != Intent.UNSUPPORTED:
                self.assertIn("no case has been created", result.answer)
            self.assertEqual(model.calls, [])
        result = await self.run_case(
            ScriptModel([]), FakeJudge(intent=Intent.UNSUPPORTED, probability=0.5)
        )
        self.assertEqual(result.disposition, "clarification")

    async def test_uncertain_information_or_action_can_read_and_answer(self):
        for intent in (Intent.INFORMATION, Intent.ACTION):
            model = ScriptModel([tool("order_detail", order_id="order-1001"), answer()])
            result = await self.run_case(
                model,
                FakeJudge(intent=intent, probability=0.68),
                question="Can I cancel my unshipped camera order?",
                operations_enabled=True,
            )
            self.assertEqual(result.disposition, "answered")
            self.assertFalse(model.calls[0]["operation_proposals_enabled"])
            self.assertIsNone(result.pending_action)
            self.assertIsNone(result.review_case)
            self.assertTrue(any(s.stage == "intent_route_check" for s in result.steps))

    async def test_order_and_policy_reads_go_directly_to_final_answer(self):
        for reads in (
            [tool("order_list"), tool("policy_search", query="cancellation")],
            [tool("policy_search", query="cancellation"), tool("order_list")],
        ):

            def final(state):
                self.assertTrue(state["final_decision_only"])
                self.assertEqual(state["tools"], {})
                observations = [
                    item for entry in state["observations"] for item in entry["results"]
                ]
                ids = tuple(
                    item["evidence_id"]
                    for item in observations
                    if item.get("source_id") in {"order-1001", "cancellation"}
                )
                return answer(
                    "The R50 order is paid and unfulfilled; cancellation requires confirmation.",
                    ids,
                )

            model = ScriptModel([*reads, final])
            result = await self.run_case(
                model, question="Can I cancel my unshipped camera order?"
            )
            self.assertEqual(result.disposition, "answered")
            self.assertEqual(len(model.calls), 3)
            requests = [
                s.details["name"] for s in result.steps if s.stage == "tool_request"
            ]
            self.assertEqual(set(requests), {"order_list", "policy_search"})
            self.assertEqual(len(requests), 2)

    async def test_precheck_rejects_before_judge(self):
        judge = FakeJudge()
        result = await self.run_case(ScriptModel([]), judge, question="???")
        self.assertEqual(result.stop_reason, "provider_or_validation_failure")
        self.assertEqual(judge.calls, [])

    async def test_missing_reference_clarifies(self):
        result = await self.run_case(
            ScriptModel(
                [
                    ModelTurn(
                        decision="Need order reference",
                        clarification="Which order do you mean?",
                    )
                ]
            )
        )
        self.assertEqual(result.disposition, "clarification")

    async def test_missing_index_and_failed_provider(self):
        result = await self.run_case(
            ScriptModel([tool("policy_search", query="returns")]), index=False
        )
        self.assertEqual(result.stop_reason, "policy_index_unavailable")
        result = await self.run_case(
            ScriptModel([RuntimeError("provider unavailable")])
        )
        self.assertEqual(result.stop_reason, "provider_or_validation_failure")
        self.assertEqual(result.steps[-1].stage, "stop")

    async def test_repeated_tool_stops_before_budget(self):
        model = ScriptModel([tool("order_list")] * 7)
        result = await self.run_case(model)
        self.assertEqual(result.stop_reason, "invalid_final_decision")
        self.assertEqual(len([s for s in result.steps if s.stage == "tool_result"]), 1)

    async def test_repeated_read_gets_terminal_answer_instead_of_fallback(self):
        model = ScriptModel(
            [
                tool("order_detail", order_id="order-1001"),
                tool("order_detail", order_id="order-1001"),
                answer(),
            ]
        )
        result = await self.run_case(model)
        self.assertEqual(result.disposition, "answered")
        self.assertTrue(model.calls[-1]["final_decision_only"])
        self.assertEqual(model.calls[-1]["tools"], {})
        self.assertEqual(len([s for s in result.steps if s.stage == "tool_result"]), 1)

    async def test_reworded_policy_search_closes_when_evidence_repeats(self):
        model = ScriptModel(
            [
                tool("policy_search", query="returns"),
                tool("policy_search", query="returns "),
                ModelTurn(
                    decision="Ask missing detail",
                    clarification="Which item would you like to return?",
                ),
            ]
        )
        result = await self.run_case(model, question="What is your return policy?")
        self.assertTrue(model.calls[-1]["final_decision_only"])
        self.assertEqual(result.disposition, "clarification")
        self.assertTrue(
            any(
                s.stage == "source_selection_closed"
                and s.details["reason"] == "no_new_evidence"
                for s in result.steps
            )
        )

    async def test_order_observations_include_product_identity(self):
        model = ScriptModel(
            [
                tool("order_list"),
                ModelTurn(
                    decision="Resolve target",
                    clarification="Would you like to cancel the EOS R50?",
                ),
            ]
        )
        await self.run_case(model)
        facts = json.loads(model.calls[-1]["observations"][0]["results"][0]["text"])
        self.assertEqual(facts["lines"][0]["product_name"], "Canon EOS R50")
        self.assertEqual(facts["lines"][0]["product_kind"], "body")

    async def test_grounding_repair_once(self):
        model = ScriptModel(
            [tool("order_detail", order_id="order-1001"), answer(), answer()]
        )
        result = await self.run_case(model, FakeJudge(grounding=0.2))
        self.assertEqual(result.stop_reason, "grounding_rejected")
        self.assertEqual(len([s for s in result.steps if s.stage == "repair"]), 1)

    async def test_numeric_and_execution_checks_before_grounder(self):
        for statement in (
            "Your order cost 999999 cents.",
            "We have refunded your order.",
        ):
            judge = FakeJudge()
            result = await self.run_case(
                ScriptModel(
                    [
                        tool("order_detail", order_id="order-1001"),
                        answer(statement),
                        answer(statement),
                    ]
                ),
                judge,
            )
            self.assertEqual(result.disposition, "handoff_needed")
            self.assertFalse(any(name == "ground" for name, _ in judge.calls))

    async def test_compatibility_lookup(self):
        model = ScriptModel(
            [
                tool("compatibility", body_id="eos-r50", lens_id="rf-s18-45"),
                answer("Canon offers this camera and lens pairing."),
            ]
        )
        result = await self.run_case(model)
        self.assertEqual(result.disposition, "answered")
        self.assertIn('"status":"compatible"', result.evidence[0].text)

    async def test_repair_can_succeed(self):
        result = await self.run_case(
            ScriptModel(
                [
                    tool("order_detail", order_id="order-1001"),
                    answer(ids=("missing",)),
                    answer(),
                ]
            )
        )
        self.assertEqual(result.disposition, "answered")
        self.assertEqual(len([s for s in result.steps if s.stage == "repair"]), 1)

    async def test_unsafe_clarification_is_replaced(self):
        result = await self.run_case(
            ScriptModel(
                [ModelTurn(decision="Ask", clarification="Your refund was processed?")]
            )
        )
        self.assertEqual(result.stop_reason, "unsafe_clarification")
        self.assertNotIn("processed", result.answer)

    async def test_model_token_budget_precedes_grounding(self):
        model = ScriptModel([tool("order_detail", order_id="order-1001"), answer()])
        original = model.turn

        async def oversized_usage(state, run_id):
            output, usage = await original(state, run_id)
            usage["input_tokens"] = 21000
            return output, usage

        model.turn = oversized_usage
        judge = FakeJudge()
        result = await self.run_case(model, judge)
        self.assertEqual(result.stop_reason, "context_or_token_budget")
        self.assertFalse(any(kind == "ground" for kind, _ in judge.calls))

    async def test_adapter_calls_sdk_with_scoped_state(self):
        response = SimpleNamespace(
            model="fake-jev",
            nouls={"supported": SimpleNamespace(noul=0.9)},
            usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 10}),
        )
        client = SimpleNamespace(system_one=AsyncMock(return_value=response))
        # Special methods must be supplied on the mock type.
        from unittest.mock import MagicMock

        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        with patch(
            "backend.customer_support.providers.AsyncTypeSafeClient",
            return_value=manager,
        ):
            judgment = await LiveJevJudge().ground(
                {"claims": [{"text": "fact", "cited_observations": []}]}
            )
        self.assertEqual(judgment.probability, 0.9)
        self.assertEqual(client.system_one.call_args.kwargs["model"], "jev-latest")
        self.assertIn("supported", client.system_one.call_args.kwargs["questions"])

    async def test_model_adapter_shape(self):
        fake = SimpleNamespace(
            iter=fake_agent_run(
                answer(), RunUsage(requests=1, input_tokens=7, output_tokens=2)
            )
        )
        with patch("backend.customer_support.providers.Agent", return_value=fake):
            provider = LiveSupportModel()
        output, usage = await provider.turn({"message": "status"}, "run-1")
        assert output.answer is not None
        self.assertEqual(output.answer.claims[0].evidence_ids, ("S1",))
        self.assertEqual(usage["input_tokens"], 7)
        self.assertEqual(fake.iter.call_args.kwargs["metadata"]["run_id"], "run-1")
        self.assertEqual(fake.iter.call_args.kwargs["usage_limits"].request_limit, 2)

    async def test_review_case_judgment_has_its_own_criteria(self):
        response = SimpleNamespace(
            model="fake",
            nouls={"supported": SimpleNamespace(noul=0.9)},
            usage=SimpleNamespace(model_dump=dict),
        )
        provider = LiveJevJudge()
        with patch.object(provider, "_ask", AsyncMock(return_value=response)) as ask:
            await provider.ground({"proposal": {"kind": "create_case"}})
            case_question = ask.call_args.args[1]["supported"]
            self.assertIn("HUMAN REVIEW CASE", case_question.instructions)
            self.assertIn("do not block recording", case_question.instructions)
            await provider.ground({"claims": []})
            self.assertNotEqual(
                case_question.criteria, ask.call_args.args[1]["supported"].criteria
            )

    def test_terminal_wire_schema_rejects_tool_and_uncited_explanation(self):
        from backend.customer_support.contracts import FinalDecisionEnvelope

        for action in (
            {
                "kind": "tool",
                "decision": "Read",
                "tool": {"name": "order_list", "arguments": {}},
            },
            {
                "kind": "clarification",
                "decision": "Ask",
                "clarification": "Which camera? It qualifies for a refund.",
            },
        ):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                FinalDecisionEnvelope.model_validate({"action": action})

    async def test_jev_adapter_shape(self):
        provider = LiveJevJudge()
        response = SimpleNamespace(
            model="fake-jev",
            nouls={
                key: SimpleNamespace(noul=value)
                for key, value in {
                    "information": 0.9,
                    "action": 0.1,
                    "human": 0.05,
                    "unsupported": 0.1,
                    "supported": 0.95,
                }.items()
            },
            usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 12}),
        )
        with patch.object(provider, "_ask", AsyncMock(return_value=response)) as ask:
            judgment = await provider.classify(
                {"message": "what is the return policy", "signals": ["policy"]}
            )
            self.assertEqual(judgment.intent, Intent.INFORMATION)
            self.assertIn("information", ask.call_args.args[1])
            grounding = await provider.ground({"claims": []})
            self.assertEqual(grounding.probability, 0.95)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.store = MockStore.load()
        self.embedder = MockEmbeddingProvider()
        self.index = ingest(self.store, self.embedder)

    def test_policy_rule_changes_render_and_invalidate_index(self):
        # Use source templates, not previously rendered observations.
        payload = json.loads(
            Path("backend/customer_support/fixtures/store_v1.json").read_text()
        )
        payload["rules"]["return_window_days"] = 45
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(json.dumps(payload))
            store = MockStore.load(path)
        self.assertIn("45 calendar days", store.policies("returns")[0].text)
        with self.assertRaises(IndexUnavailable):
            search(store, self.index, self.embedder, "return window")

    def test_hybrid_retrieval(self):
        passages, trace = search(
            self.store,
            self.index,
            self.embedder,
            "returns refund review within delivery window",
        )
        self.assertEqual(passages[0].policy_id, "returns")
        self.assertTrue(trace["lexical"])
        self.assertTrue(trace["semantic"])
        self.assertLessEqual(len(passages), 3)
        self.assertNotIn("order-1001", self.index.model_dump_json())

    def test_malformed_missing_model_and_dimension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.json"
            with self.assertRaises(IndexUnavailable):
                load_index(path)
            path.write_text("{}")
            with self.assertRaises(IndexUnavailable):
                load_index(path)
        wrong = self.index.model_copy(update={"embedding_model": "other"})
        with patch.object(self.embedder, "embed_query") as query:
            with self.assertRaises(IndexUnavailable):
                search(self.store, wrong, self.embedder, "returns")
            query.assert_not_called()
        with (
            patch.object(self.embedder, "embed_query", return_value=(1.0,)),
            self.assertRaises(ValueError),
        ):
            search(self.store, self.index, self.embedder, "returns")
        with self.assertRaises(ValidationError):
            PolicyIndex.model_validate(
                {
                    **self.index.model_dump(),
                    "passages": [
                        {
                            **self.index.passages[0].model_dump(),
                            "vector": [float("nan")],
                        }
                    ],
                }
            )


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                Base.metadata.tables[model.__tablename__]
                for model in (
                    LlmRun,
                    SupportDemoSession,
                    SupportConversation,
                    SupportOutput,
                    SupportOrder,
                    SupportProposal,
                    SupportReceipt,
                    SupportCase,
                    SupportTask,
                )
            ],
        )

        @contextmanager
        def sessions():
            with Session(self.engine, expire_on_commit=False) as db:
                try:
                    yield db
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise

        self.repo = SupportRepository(sessions)
        self.store = MockStore.load()
        self.embedder = MockEmbeddingProvider()
        self.model = ScriptModel(
            [tool("order_detail", order_id="order-1001"), answer()]
        )
        self.runtime = api.Runtime(
            self.store,
            self.model,
            FakeJudge(),
            ingest(self.store, self.embedder),
            self.embedder,
        )
        self.app = FastAPI()
        self.app.include_router(api.router)
        self.app.dependency_overrides[api.repository] = lambda: self.repo
        self.app.dependency_overrides[api.runtime] = lambda: self.runtime
        self.client = TestClient(self.app)
        self.base = "/agent/customer_support"
        response = self.client.post(
            self.base + "/sessions", json={"customer_id": "customer-alex"}
        )
        self.token = response.json()["token"]
        self.headers = {"Authorization": "Bearer " + self.token}
        self.conversation = self.client.post(
            self.base + "/conversations", headers=self.headers
        ).json()["conversation_id"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_api_saved_output_and_owned_history(self):
        response = self.client.post(
            self.base + f"/conversations/{self.conversation}/messages",
            headers=self.headers,
            json={"message": "Where is order-1001?"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["disposition"], "answered")
        history = self.client.get(
            self.base + f"/conversations/{self.conversation}", headers=self.headers
        ).json()
        self.assertEqual(history[0]["response"], result)
        with Session(self.engine) as db:
            runs = list(db.scalars(select(LlmRun)))
            self.assertEqual(runs[0].system_key, "customer_support")
            self.assertEqual(runs[0].status, "completed")
            conversation = db.get(SupportConversation, UUID(self.conversation))
            assert conversation is not None
            self.assertIsNone(conversation.active_run_id)
        sam = self.client.post(
            self.base + "/sessions", json={"customer_id": "customer-sam"}
        ).json()["token"]
        foreign = self.client.get(
            self.base + f"/conversations/{self.conversation}",
            headers={"Authorization": "Bearer " + sam},
        )
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(
            self.client.post(
                self.base + f"/conversations/{self.conversation}/messages",
                headers=self.headers,
                json={"message": "hi", "customer_id": "customer-sam"},
            ).status_code,
            422,
        )

    def test_followup_saved_context_and_fresh_lookup(self):
        self.client.post(
            self.base + f"/conversations/{self.conversation}/messages",
            headers=self.headers,
            json={"message": "Where is order-1001?"},
        )
        self.model.script = [tool("order_detail", order_id="order-1001"), answer()]
        response = self.client.post(
            self.base + f"/conversations/{self.conversation}/messages",
            headers=self.headers,
            json={"message": "And that order now?"},
        )
        self.assertEqual(response.json()["disposition"], "answered")
        self.assertEqual(
            self.model.calls[2]["recent_turns"][0]["question"], "Where is order-1001?"
        )
        self.assertEqual(
            len(
                self.repo.history(
                    UUID(self.token),
                    UUID(self.conversation),
                )
            ),
            2,
        )

    def test_stream_order_and_failure_persisted(self):
        self.model.script = [RuntimeError("provider down")]
        response = self.client.post(
            self.base + f"/conversations/{self.conversation}/messages/stream",
            headers=self.headers,
            json={"message": "status?"},
        )
        self.assertEqual(response.status_code, 200)
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(events[0]["type"], "started")
        self.assertEqual(events[-1]["type"], "completed")
        self.assertEqual(
            events[-1]["result"]["stop_reason"], "provider_or_validation_failure"
        )
        self.assertEqual(
            [e["step"]["sequence"] for e in events if e["type"] == "step"],
            list(range(1, len([e for e in events if e["type"] == "step"]) + 1)),
        )
        with Session(self.engine) as db:
            self.assertEqual(next(iter(db.scalars(select(LlmRun)))).status, "failed")
            self.assertEqual(list(db.scalars(select(SupportCase))), [])

    def test_failed_wire_validation_preserves_usage_without_creating_case(self):
        from backend.customer_support.providers import ModelBoundaryFailure

        self.model.script = [
            ModelBoundaryFailure(
                "UnexpectedModelBehavior",
                "Mixed decision",
                {"requests": 2, "input_tokens": 80},
                [{"part_kind": "retry-prompt"}],
            )
        ]
        response = self.client.post(
            self.base + f"/conversations/{self.conversation}/messages",
            headers=self.headers,
            json={"message": "Can I cancel my camera order?"},
        )
        result = response.json()
        self.assertEqual(result["stop_reason"], "provider_or_validation_failure")
        self.assertEqual(result["usage"]["failed_model"]["requests"], 2)
        self.assertIsNone(result["review_case"])
        with Session(self.engine) as db:
            self.assertEqual(list(db.scalars(select(SupportCase))), [])

    def test_busy_conversation_rejects_second_run(self):
        from uuid import UUID

        self.repo.begin(UUID(self.token), UUID(self.conversation))
        with self.assertRaises(ConversationBusy):
            self.repo.begin(UUID(self.token), UUID(self.conversation))
        self.assertEqual(
            self.client.post(
                self.base + f"/conversations/{self.conversation}/messages",
                headers=self.headers,
                json={"message": "status"},
            ).status_code,
            409,
        )


class PolicyRuleTests(unittest.TestCase):
    def test_rule_schema_rejects_unsafe_or_untyped_values(self):
        from backend.customer_support.contracts import PolicyRules

        base = MockStore.load().fixture.rules.model_dump()
        for patch_values in (
            {"ai_refund_execution": True},
            {"return_window_days": "30"},
            {"return_window_days": 0},
            {"cancellation_states": ("shipped",)},
        ):
            with self.subTest(values=patch_values), self.assertRaises(ValidationError):
                PolicyRules.model_validate({**base, **patch_values})

    def test_deterministic_window_boundary_and_state(self):
        from datetime import timedelta

        from backend.customer_support.store import review_order

        store = MockStore.load()
        customer = store.sign_in("customer-alex")
        delivered = require_order(customer, "order-1004")
        for days, expected in [(30, True), (31, False)]:
            observation = delivered.model_copy(
                update={
                    "delivered_on": store.fixture.scenario_date - timedelta(days=days)
                }
            )
            self.assertEqual(
                review_order(observation, store).return_within_review_window, expected
            )
        self.assertTrue(
            review_order(
                require_order(customer, "order-1001"), store
            ).cancellation_state_eligible
        )
        self.assertFalse(
            review_order(
                require_order(customer, "order-1002"), store
            ).cancellation_state_eligible
        )
        self.assertFalse(
            review_order(
                require_order(customer, "order-1003"), store
            ).address_change_state_eligible
        )
        old = require_order(store.sign_in("customer-sam"), "order-2002")
        self.assertFalse(review_order(old, store).warranty_within_review_window)
        self.assertFalse(review_order(delivered, store).action_executed)


if __name__ == "__main__":
    unittest.main()


class LiveAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        guard = patch(
            "pydantic_ai.models.openai.OpenAIResponsesModel.request",
            side_effect=AssertionError("Live providers are forbidden in offline tests"),
        )
        guard.start()
        self.addCleanup(guard.stop)

    async def test_terminal_schema_is_used_by_real_adapter(self):
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        from backend.customer_support.contracts import DecisionEnvelope

        def respond(messages, info):
            schema = json.dumps(info.output_tools[0].parameters_json_schema)
            self.assertNotIn('"ToolDecision"', schema)
            self.assertIn('"AnswerDecision"', schema)
            draft = answer().answer
            assert draft is not None
            action = {
                "kind": "answer",
                "decision": "Answer from completed observations",
                "answer": draft.model_dump(mode="json"),
            }
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"action": action})]
            )

        adapter = LiveSupportModel()
        adapter.agent = Agent(
            FunctionModel(respond), output_type=DecisionEnvelope, retries=1
        )
        output, usage = await adapter.turn({"final_decision_only": True}, "fake-run")
        self.assertIsNotNone(output.answer)
        self.assertEqual(usage["requests"], 1)

    async def test_usage_serialization_matches_real_provider_shape(self):
        from decimal import Decimal
        from unittest.mock import patch

        from pydantic_ai.usage import RunUsage

        from backend.customer_support.providers import LiveSupportModel

        adapter = LiveSupportModel()
        usage = RunUsage(
            input_tokens=1138,
            output_tokens=98,
            requests=1,
            cost=Decimal("0.0003452"),
            details={"reasoning_tokens": 51},
        )
        with patch.object(
            adapter.agent, "iter", fake_agent_run(tool("order_list"), usage)
        ):
            output, counts = await adapter.turn(
                {"remaining_token_budget": 19000}, "fake-run"
            )
        self.assertEqual(counts["cost"], "0.0003452")
        self.assertEqual(counts["details"]["reasoning_tokens"], 51)
        self.assertIsNotNone(output.tool)
        import json

        json.dumps(counts)

    async def test_available_tool_schema_excludes_completed_reads_and_repairs_invalid_name(
        self,
    ):
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        from backend.customer_support.contracts import DecisionEnvelope

        calls = 0

        def respond(messages, info):
            nonlocal calls
            calls += 1
            schema = json.dumps(info.output_tools[0].parameters_json_schema)
            self.assertIn('"policy_search"', schema)
            self.assertNotIn('"order_detail"', schema)
            name = "order_detail" if calls == 1 else "policy_search"
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "action": {
                                "kind": "tool",
                                "decision": "Retrieve missing evidence",
                                "tool": {
                                    "name": name,
                                    "arguments": {"query": "cancellation"},
                                },
                            }
                        },
                    )
                ]
            )

        adapter = LiveSupportModel()
        adapter.agent = Agent(
            FunctionModel(respond), output_type=DecisionEnvelope, retries=1
        )
        output, usage = await adapter.turn(
            {"tools": {"policy_search": {"query": "bounded text"}}}, "fake-run"
        )
        self.assertIsNotNone(output.tool)
        assert output.tool is not None
        self.assertEqual(output.tool.name, "policy_search")
        self.assertEqual(usage["requests"], 2)

    async def test_mixed_output_repairs_once_through_real_adapter(self):
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        from backend.customer_support.contracts import DecisionEnvelope

        calls = []

        def respond(messages, info):
            calls.append(messages)
            action: dict[str, Any] = {
                "kind": "clarification",
                "decision": "Ask which item",
                "clarification": "Which camera do you mean?",
            }
            if len(calls) == 1:
                action["tool"] = {"name": "order_list", "arguments": {}}
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"action": action})]
            )

        adapter = LiveSupportModel()
        adapter.agent = Agent(
            FunctionModel(respond), output_type=DecisionEnvelope, retries=1
        )
        result, usage = await adapter.turn({"message": "Which order?"}, "fake-run")
        self.assertEqual(result.clarification, "Which camera do you mean?")
        self.assertEqual(usage["requests"], 2)
        self.assertEqual(usage["output_repairs"], 1)
        self.assertTrue(
            any(
                part.part_kind == "retry-prompt"
                for message in calls[-1]
                for part in message.parts
            )
        )

    async def test_exhausted_validation_preserves_diagnostics_and_usage(self):
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        from backend.customer_support.contracts import DecisionEnvelope
        from backend.customer_support.providers import ModelBoundaryFailure

        def respond(messages, info):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "action": {
                                "kind": "clarification",
                                "decision": "Ask",
                                "clarification": "Which order?",
                                "tool": {"name": "order_list", "arguments": {}},
                            }
                        },
                    )
                ]
            )

        adapter = LiveSupportModel()
        adapter.agent = Agent(
            FunctionModel(respond), output_type=DecisionEnvelope, retries=1
        )
        with self.assertRaises(ModelBoundaryFailure) as caught:
            await adapter.turn({"message": "Which order?"}, "fake-run")
        self.assertEqual(caught.exception.usage["requests"], 2)
        self.assertEqual(caught.exception.error_type, "UnexpectedModelBehavior")
        self.assertTrue(caught.exception.diagnostics)
