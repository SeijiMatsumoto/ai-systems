"""Transactional action and case workflows against an isolated database; no providers."""

import copy
import unittest
from typing import TypeVar
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session

from backend.customer_support.actions import confirm
from backend.customer_support.contracts import (
    Address,
    AddressProposal,
    CancelProposal,
    CaseCategory,
    CaseRequest,
    ConfirmationRequest,
    Intent,
    ModelTurn,
    TaskRoute,
)
from backend.customer_support.repository import SupportRepository
from backend.customer_support.tests import test_workflow
from backend.customer_support.tests.test_workflow import (
    FakeJudge,
    answer,
    require_order,
    tool,
)
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

Row = TypeVar("Row", bound=Base)


def require_row(db: Session, model: type[Row], key: object) -> Row:
    row = db.get(model, key)
    assert row is not None
    return row


class ActionTests(test_workflow.ApiTests):
    def test_eligibility_then_varied_order_followups_use_saved_target(self):
        listed = self.send("What are my orders?")
        self.assertEqual(
            len([item for item in listed["evidence"] if item["kind"] == "order"]), 5
        )
        self.runtime.judge = FakeJudge(intent=Intent.INFORMATION)
        self.runtime.judge.route_decision = TaskRoute(route="clarify", probability=0.77)

        def eligibility(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            return answer(
                "Your Canon EOS R50 order is paid and unfulfilled.",
                tuple(item["evidence_id"] for item in evidence),
            )

        self.model.script = [
            tool("order_detail", order_id="order-1001"),
            tool("policy_search", query="cancellation"),
            eligibility,
        ]
        first = self.send("can i cancel the canon EOS r50?")
        self.assertEqual(first["stop_reason"], "verified")
        prompts = (
            ("How much was that order?", "The item total was $500."),
            ("How much did it cost?", "The item total was $500."),
            ("how much did I pay for that?", "The item total was $500."),
            ("Has that shipped yet?", "Your order is unfulfilled and has not shipped."),
            ("When was that order placed?", "Your order was placed on 2026-09-30."),
            ("Where is that order?", "Your order is unfulfilled."),
            (
                "Has that order shipped yet?",
                "Your order is unfulfilled and has not shipped.",
            ),
            ("What items are in this order?", "Your order contains one Canon EOS R50."),
            ("Is that order paid?", "Your order is paid."),
            (
                "What is the status of the same order?",
                "Your order is paid and unfulfilled.",
            ),
        )
        for prompt, text in prompts:
            with self.subTest(prompt=prompt):

                def followup(state, text=text):
                    self.assertEqual(
                        state["references"]["owned_order_ids"], ["order-1001"]
                    )
                    evidence = [
                        item
                        for entry in state["observations"]
                        for item in entry["results"]
                        if item.get("kind") == "order"
                    ]
                    self.assertEqual(len(evidence), 1)
                    self.assertEqual(evidence[0]["source_id"], "order-1001")
                    return answer(text, (evidence[0]["evidence_id"],))

                self.model.script = [followup]
                before = len(self.model.calls)
                result = self.send(prompt)
                self.assertEqual(result["stop_reason"], "verified")
                self.assertEqual(result["task"]["task_id"], first["task"]["task_id"])
                self.assertEqual(len(self.model.calls), before + 1)
                self.assertEqual(result["answer"], text)
                self.assertIsNone(result["pending_action"])
                self.assertIsNone(result["review_case"])
        self.assertFalse(
            any(name == "continuation" for name, _ in self.runtime.judge.calls)
        )

    def test_eligibility_then_policy_question_preserves_exact_task(self):
        self.runtime.judge = FakeJudge(intent=Intent.INFORMATION)
        # Make the semantic router fail if called: this reference is deterministic.
        self.runtime.judge.route_decision = TaskRoute(route="clarify", probability=0.95)

        def eligibility(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            return answer(
                "Your Canon EOS R50 is unfulfilled and qualifies for cancellation with confirmation.",
                tuple(item["evidence_id"] for item in evidence),
            )

        self.model.script = [
            tool("order_detail", order_id="order-1001"),
            tool("policy_search", query="cancellation"),
            eligibility,
        ]
        first = self.send("Can I cancel my unshipped camera order?")
        self.assertEqual(first["stop_reason"], "verified")
        self.assertEqual(first["task"]["selected_order_ids"], ["order-1001"])

        def policy_answer(state):
            self.assertEqual(state["references"]["owned_order_ids"], ["order-1001"])
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if item.get("kind") == "policy"
            ]
            self.assertTrue(evidence)
            return answer(
                "Cancellation requires a paid, unfulfilled order and your confirmation.",
                tuple(item["evidence_id"] for item in evidence),
            )

        self.model.script = [policy_answer]
        result = self.send("What does the cancellation policy require for that order?")
        self.assertEqual(result["stop_reason"], "verified")
        self.assertEqual(result["task"]["task_id"], first["task"]["task_id"])
        self.assertIsNone(result["pending_action"])
        self.assertFalse(
            any(name == "continuation" for name, _ in self.runtime.judge.calls)
        )
        self.assertEqual(
            [
                step["details"]["name"]
                for step in result["steps"]
                if step["stage"] == "tool_request"
            ],
            ["order_detail"],
        )

    def test_followup_reuses_policy_but_refreshes_order_and_accumulates_resources(self):
        first = self.propose()
        task_id = first["task"]["task_id"]
        self.assertTrue(first["task"]["saved_policy"])
        # Recreate the repository to ensure reuse comes from persistence.
        self.repo = SupportRepository(self.repo.session_factory)
        self.runtime.judge = FakeJudge(intent=Intent.INFORMATION)

        def explanation(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            self.assertTrue(any(item["kind"] == "order" for item in evidence))
            return answer(
                "Your unfulfilled order can be cancelled after confirmation.",
                tuple(item["evidence_id"] for item in evidence),
            )

        self.model.script = [explanation]
        result = self.send("Can I cancel that order under the policy?")
        self.assertEqual(result["stop_reason"], "verified")
        self.assertEqual(result["task"]["task_id"], task_id)
        requests = [
            step["details"]["name"]
            for step in result["steps"]
            if step["stage"] == "tool_request"
        ]
        self.assertEqual(requests, ["order_detail"])
        reuse = next(
            step for step in result["steps"] if step["stage"] == "policy_reuse_check"
        )
        self.assertTrue(reuse["details"]["reused"])
        self.assertEqual(
            reuse["details"]["reused"][0]["source_run_id"], first["run_id"]
        )
        self.assertEqual(result["task"]["resources"]["executions"], 2)
        self.assertEqual(
            result["task"]["resources"]["tokens"],
            first["task"]["resources"]["tokens"]
            + sum(
                value.get("input_tokens", 0) + value.get("output_tokens", 0)
                for value in result["usage"].values()
            ),
        )
        self.assertEqual(
            result["task"]["resources"]["tool_calls"],
            first["task"]["resources"]["tool_calls"] + 1,
        )

    def test_reused_policy_never_reuses_mutable_order_state(self):
        self.propose()
        with Session(self.engine) as db, db.begin():
            row = require_row(db, SupportOrder, "order-1001")
            payload = copy.deepcopy(row.payload)
            payload["fulfillment"] = "shipped"
            row.payload = payload
            row.version += 1
        self.runtime.judge = FakeJudge(intent=Intent.INFORMATION)

        def current_answer(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            order = next(item for item in evidence if item["kind"] == "order")
            import json

            self.assertEqual(json.loads(order["text"])["fulfillment"], "shipped")
            return answer("Your order has shipped.", (order["evidence_id"],))

        self.model.script = [current_answer]
        result = self.send("Can I cancel that order under the policy?")
        self.assertEqual(result["stop_reason"], "verified")

    def test_stale_policy_is_invalidated_before_followup_answer(self):
        from backend.customer_support.retrieval import ingest

        first = self.propose()
        policies = tuple(
            p.model_copy(update={"revision": "revised-policy"})
            for p in self.store.fixture.policies
        )
        self.store.fixture = self.store.fixture.model_copy(
            update={"policies": policies}
        )
        self.runtime.index = ingest(self.store, self.runtime.embedder)
        self.runtime.judge = FakeJudge(intent=Intent.INFORMATION)

        def explanation(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            policy = [item for item in evidence if item["kind"] == "policy"]
            self.assertTrue(policy)
            self.assertTrue(
                all(item["locator"].startswith("revised-policy:") for item in policy)
            )
            return answer(
                "Cancellation requires confirmation.",
                tuple(item["evidence_id"] for item in policy),
            )

        self.model.script = [tool("policy_search", query="cancellation"), explanation]
        result = self.send("Can I cancel that order under the policy?")
        self.assertEqual(result["stop_reason"], "verified")
        reuse = next(
            step for step in result["steps"] if step["stage"] == "policy_reuse_check"
        )
        self.assertEqual(reuse["details"]["reused"], [])
        self.assertTrue(reuse["details"]["invalidated"])
        self.assertEqual(result["task"]["task_id"], first["task"]["task_id"])

    def test_failed_provider_usage_is_charged_to_same_task(self):
        from backend.customer_support.providers import ModelBoundaryFailure

        first = self.propose()
        self.runtime.judge = FakeJudge(intent=Intent.INFORMATION)
        self.model.script = [
            ModelBoundaryFailure(
                "ValidationError",
                "bad response",
                {"input_tokens": 500, "output_tokens": 30},
                [],
            )
        ]
        result = self.send("Can I cancel that order under the policy?")
        self.assertEqual(result["stop_reason"], "provider_or_validation_failure")
        self.assertIsNone(result["review_case"])
        self.assertEqual(
            result["task"]["resources"]["tokens"],
            first["task"]["resources"]["tokens"] + 572,
        )
        self.assertEqual(result["task"]["resources"]["executions"], 2)

    def test_exhausted_task_blocks_models_but_specific_confirmation_still_works(self):
        first = self.propose()
        with Session(self.engine) as db, db.begin():
            row = require_row(db, SupportTask, UUID(first["task"]["task_id"]))
            checkpoint = copy.deepcopy(row.checkpoint)
            checkpoint["resources"] = {
                "executions": 12,
                "tokens": 60000,
                "tool_calls": 24,
            }
            row.checkpoint = checkpoint
        before = len(self.model.calls)
        self.runtime.judge = FakeJudge(intent=Intent.INFORMATION)
        result = self.send("Can I cancel that order under the policy?")
        self.assertEqual(result["stop_reason"], "task_resource_budget")
        self.assertEqual(len(self.model.calls), before)
        self.assertEqual(self.runtime.judge.calls, [])
        self.assertIsNone(result["review_case"])
        self.assertEqual(self.decide(first).status_code, 200)

    def test_routing_timeout_preserves_tasks_and_saves_failure_without_case(self):
        first = self.propose()
        second = self.propose(
            "change_address",
            address=Address(
                line1="200 Demo Road",
                city="Exampleville",
                postal_code="12345",
                country="US",
            ),
        )
        before = len(self.model.calls)
        with patch.object(
            self.runtime.judge,
            "route_task",
            AsyncMock(side_effect=TimeoutError("provider timeout")),
        ):
            result = self.send("That one")
        self.assertEqual(result["stop_reason"], "provider_or_validation_failure")
        self.assertIsNone(result["review_case"])
        self.assertEqual(len(self.model.calls), before)
        with Session(self.engine) as db:
            self.assertEqual(
                require_row(db, LlmRun, UUID(result["run_id"])).status, "failed"
            )
            for response in (first, second):
                self.assertEqual(
                    require_row(
                        db, SupportTask, UUID(response["task"]["task_id"])
                    ).checkpoint["status"],
                    "awaiting_approval",
                )

    def test_topic_switch_keeps_both_tasks_and_returns_to_older_one(self):
        first = self.propose()
        second = self.propose(
            "change_address",
            address=Address(
                line1="200 Demo Road",
                city="Exampleville",
                postal_code="12345",
                country="US",
            ),
        )
        self.assertEqual(second["task"]["kind"], "change_address")
        self.assertNotEqual(first["task"]["task_id"], second["task"]["task_id"])
        assert isinstance(self.runtime.judge, FakeJudge)
        self.runtime.judge.route_decision = TaskRoute(
            route="resume", task_id=first["task"]["task_id"], probability=0.95
        )
        before = len(self.model.calls)
        resumed = self.send("Back to my earlier request")
        self.assertEqual(resumed["task"]["task_id"], first["task"]["task_id"])
        self.assertEqual(resumed["stop_reason"], "explicit_confirmation_required")
        self.assertEqual(len(self.model.calls), before)
        with Session(self.engine) as db:
            self.assertEqual(
                require_row(
                    db, SupportTask, UUID(second["task"]["task_id"])
                ).checkpoint["status"],
                "awaiting_approval",
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportProposal)), 2
            )

    def test_ambiguous_reply_preserves_both_pending_tasks(self):
        first = self.propose()
        self.propose(
            "change_address",
            address=Address(
                line1="200 Demo Road",
                city="Exampleville",
                postal_code="12345",
                country="US",
            ),
        )
        before = len(self.model.calls)
        result = self.send("That one")
        self.assertEqual(result["stop_reason"], "task_reference_ambiguous")
        self.assertIsNone(result["task"])
        self.assertEqual(len(self.model.calls), before)
        with Session(self.engine) as db:
            self.assertEqual(
                require_row(db, SupportTask, UUID(first["task"]["task_id"])).checkpoint[
                    "status"
                ],
                "awaiting_approval",
            )

    def test_correction_discards_old_target_and_rechecks_new_one(self):
        self.runtime.judge = FakeJudge()
        self.model.script = [tool("order_detail", order_id="order-1001"), answer()]
        first = self.send("Can I cancel my camera order?")
        self.runtime.judge.route_decision = TaskRoute(
            route="correct", task_id=first["task"]["task_id"], probability=0.95
        )
        self.model.script = [
            tool("order_detail", order_id="order-1002"),
            answer("The lens order has a shipping label created."),
        ]
        corrected = self.send("Actually, I meant order-1002")
        self.assertEqual(corrected["task"]["task_id"], first["task"]["task_id"])
        self.assertEqual(corrected["task"]["selected_order_ids"], ["order-1002"])
        self.assertEqual(self.model.calls[-2]["references"]["owned_order_ids"], [])

    def test_abandonment_requires_card_rejection_when_approval_is_pending(self):
        first = self.propose()
        before = len(self.model.calls)
        result = self.send("Never mind")
        self.assertEqual(result["stop_reason"], "explicit_rejection_required")
        self.assertEqual(result["task"]["status"], "awaiting_approval")
        self.assertEqual(len(self.model.calls), before)
        self.assertEqual(
            self.decide(first, "reject").json()["disposition"], "action_rejected"
        )

    def test_clarification_can_be_abandoned_without_creating_a_case(self):
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)
        self.model.script = [
            ModelTurn(
                decision="Need target",
                clarification="Which item would you like to cancel?",
            )
        ]
        first = self.send("Cancel an order")
        result = self.send("Never mind")
        self.assertEqual(result["task"]["task_id"], first["task"]["task_id"])
        self.assertEqual(result["task"]["status"], "abandoned")
        self.assertIsNone(result["review_case"])
        self.assertIsNone(result["pending_action"])

    def test_resumed_task_refreshes_target_without_model_discovery_turn(self):
        self.runtime.judge = FakeJudge()
        self.model.script = [tool("order_detail", order_id="order-1001"), answer()]
        self.send("Can I cancel my unshipped camera order?")
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)
        before = len(self.model.calls)

        def proposal(state):
            self.assertNotIn("order_detail", state["tools"])
            self.assertTrue(state["final_decision_only"])
            evidence = [
                item for entry in state["observations"] for item in entry["results"]
            ]
            return ModelTurn(
                decision="Propose cancellation",
                proposal=CancelProposal(
                    kind="cancel_order",
                    order_id="order-1001",
                    evidence_ids=tuple(item["evidence_id"] for item in evidence),
                ),
            )

        self.model.script = [tool("policy_search", query="cancellation"), proposal]
        result = self.send("Yes, cancel please")
        self.assertEqual(result["disposition"], "awaiting_confirmation")
        self.assertEqual(len(self.model.calls) - before, 2)
        self.assertEqual(
            [
                s["details"]["name"]
                for s in result["steps"]
                if s["stage"] == "tool_request"
            ],
            ["order_detail", "policy_search"],
        )
        self.assertFalse(
            any(s["stage"] == "duplicate_tool_check" for s in result["steps"])
        )

    def test_followup_cancellation_reuses_target_and_completes_policy_evidence(self):
        self.runtime.judge = FakeJudge()
        self.model.script = [
            tool("order_detail", order_id="order-1001"),
            test_workflow.answer("Your Canon EOS R50 order is paid and unfulfilled."),
        ]
        initial = self.send("Can I cancel my unshipped camera order?")
        task_id = initial["task"]["task_id"]
        self.repo = SupportRepository(self.repo.session_factory)
        self.client.close()
        self.app = FastAPI()
        self.app.include_router(test_workflow.api.router)
        self.app.dependency_overrides[test_workflow.api.repository] = lambda: self.repo
        self.app.dependency_overrides[test_workflow.api.runtime] = lambda: self.runtime
        self.client = TestClient(self.app)
        for _ in range(5):
            self.send("What are my orders?")
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)

        def proposal(state):
            self.assertEqual(state["references"]["owned_order_ids"], ["order-1001"])
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            return ModelTurn(
                decision="Propose cancellation",
                proposal=CancelProposal(
                    kind="cancel_order",
                    order_id="order-1001",
                    evidence_ids=tuple(item["evidence_id"] for item in evidence),
                ),
            )

        self.model.script = [
            tool("order_detail", order_id="order-1001"),
            tool("order_detail", order_id="order-1001"),
            tool("policy_search", query="cancellation"),
            proposal,
        ]
        response = self.send("Yes, cancel please")
        self.assertEqual(response["disposition"], "awaiting_confirmation")
        self.assertIsNotNone(response["pending_action"])
        self.assertIsNone(response["receipt"])
        self.assertEqual(response["task"]["task_id"], task_id)
        self.assertEqual(response["task"]["status"], "awaiting_approval")
        self.assertEqual(response["task"]["version"], 3)
        self.assertTrue(any(s["stage"] == "task_resumed" for s in response["steps"]))
        requests = [
            s["details"]["name"]
            for s in response["steps"]
            if s["stage"] == "tool_request"
        ]
        self.assertEqual(requests, ["order_detail", "policy_search"])
        calls = len(self.model.calls)
        repeat = self.send("Yes, cancel please")
        self.assertEqual(repeat["stop_reason"], "explicit_confirmation_required")
        self.assertEqual(repeat["task"]["status"], "awaiting_approval")
        self.assertEqual(len(self.model.calls), calls)
        with Session(self.engine) as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportProposal)), 1
            )
        decided = self.decide(response).json()
        self.assertEqual(decided["task"]["task_id"], task_id)
        self.assertEqual(decided["task"]["status"], "completed")

    def test_clarification_checkpoint_resumes_without_original_transcript(self):
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)
        self.model.script = [
            ModelTurn(
                decision="Need target",
                clarification="Which order would you like to cancel?",
            )
        ]
        initial = self.send("Cancel an order")
        self.assertEqual(initial["task"]["status"], "awaiting_clarification")
        self.repo = SupportRepository(self.repo.session_factory)
        self.model.script = [tool("order_detail", order_id="order-1001"), answer()]
        result = self.send("order-1001")
        self.assertEqual(result["task"]["task_id"], initial["task"]["task_id"])
        self.assertEqual(
            self.model.calls[-1]["task_checkpoint"]["pending_question"],
            "Which order would you like to cancel?",
        )

    def test_checkpoint_is_scoped_to_conversation_and_unrelated_messages(self):
        initial = self.propose()
        calls = len(self.model.calls)
        unrelated = self.send("What are my orders?")
        self.assertIsNone(unrelated["task"])
        self.assertEqual(len(self.model.calls), calls)
        with Session(self.engine) as db:
            checkpoint = require_row(db, SupportTask, UUID(initial["task"]["task_id"]))
            self.assertEqual(
                checkpoint.checkpoint["version"], initial["task"]["version"]
            )
        other = self.repo.create_conversation(UUID(self.token))
        run, _, _ = self.repo.begin(UUID(self.token), other)
        from backend.customer_support.contracts import TaskRoute

        checkpoint, resumed = self.repo.apply_task_route(
            UUID(self.token), other, run, "Yes", TaskRoute(route="new")
        )
        self.assertIsNone(checkpoint)
        self.assertFalse(resumed)
        self.repo.abort(UUID(self.token), other, run)

    # Reuse the isolated API setup while retaining its read-only regressions.
    def send(self, message):
        response = self.client.post(
            self.base + f"/conversations/{self.conversation}/messages",
            headers=self.headers,
            json={"message": message},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def propose(
        self, kind="cancel_order", order="order-1001", address: Address | None = None
    ):
        if kind != "cancel_order":
            assert address is not None
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)

        def proposal(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            policy = next(item for item in evidence if item["kind"] == "policy")
            order_fact = next(item for item in evidence if item["kind"] == "order")
            ids = (policy["evidence_id"], order_fact["evidence_id"])
            if kind == "cancel_order":
                op = CancelProposal(
                    kind="cancel_order", order_id=order, evidence_ids=ids
                )
            else:
                assert address is not None
                op = AddressProposal(
                    kind="change_address",
                    order_id=order,
                    address=address,
                    evidence_ids=ids,
                )
            return ModelTurn(decision="Propose checked change", proposal=op)

        self.model.script = [
            tool("policy_search", query="cancellation address change unfulfilled"),
            tool("order_detail", order_id=order),
            proposal,
        ]
        if kind == "cancel_order":
            message = f"Cancel {order}"
        else:
            assert address is not None
            message = f"Change {order} to {address.line1}, {address.city} {address.postal_code}, US"
        return self.send(message)

    def decide(self, result, decision="confirm", headers=None):
        return self.client.post(
            self.base
            + f"/conversations/{self.conversation}/proposals/{result['pending_action']['proposal_id']}/decision",
            headers=headers or self.headers,
            json={"decision": decision},
        )

    def test_cancel_requires_confirmation_and_persists(self):
        result = self.propose()
        self.assertEqual(result["disposition"], "awaiting_confirmation")
        store = self.repo.customer_store(self.store, "customer-alex")
        self.assertEqual(require_order(store, "order-1001").state, "paid")
        response = self.decide(result)
        self.assertEqual(response.status_code, 200, response.text)
        receipt = response.json()["receipt"]
        self.assertEqual(receipt["outcome"], "executed")
        self.assertFalse(receipt["refund_executed"])
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "cancelled",
        )
        # A fresh sign-in seeds only missing records, preserving mutations.
        self.repo.sign_in(self.store, "customer-alex")
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "cancelled",
        )
        repeated = self.decide(result)
        self.assertEqual(repeated.json(), response.json())
        with Session(self.engine) as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportReceipt)), 1
            )
            self.assertEqual(require_row(db, SupportOrder, "order-1001").version, 2)

    def test_address_change_and_rejection(self):
        address = Address(
            line1="200 Demo Road",
            city="Exampleville",
            postal_code="12345",
            country="US",
        )
        result = self.propose("change_address", address=address)
        self.assertEqual(result["pending_action"]["address"], address.model_dump())
        response = self.decide(result)
        self.assertEqual(response.json()["receipt"]["outcome"], "executed")
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).address,
            address,
        )
        result = self.propose()
        self.assertEqual(
            self.decide(result, "reject").json()["receipt"]["outcome"], "rejected"
        )
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "paid",
        )
        self.assertEqual(self.decide(result).status_code, 400)

    def test_stale_order_blocks_and_saves_case(self):
        result = self.propose()
        with Session(self.engine) as db:
            row = require_row(db, SupportOrder, "order-1001")
            payload = copy.deepcopy(row.payload)
            payload["fulfillment"] = "label_created"
            db.execute(
                update(SupportOrder)
                .where(SupportOrder.order_id == "order-1001")
                .values(version=2, payload=payload)
            )
            db.commit()
        response = self.decide(result)
        self.assertEqual(response.json()["receipt"]["outcome"], "blocked")
        self.assertEqual(response.json()["review_case"]["status"], "pending_review")
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "paid",
        )
        self.assertEqual(self.decide(result).json(), response.json())

    def test_stale_policy_blocks(self):
        result = self.propose()
        changed = self.store.fixture.model_copy(
            update={
                "rules": self.store.fixture.rules.model_copy(
                    update={"return_window_days": 31}
                )
            }
        )
        with patch(
            "backend.customer_support.api.MockStore.load",
            return_value=type(self.store)(changed),
        ):
            response = self.decide(result)
        self.assertEqual(response.json()["receipt"]["outcome"], "blocked")

    def test_ineligible_initial_order_creates_review_case(self):
        result = self.propose(order="order-1002")
        self.assertEqual(result["disposition"], "case_created")
        self.assertIsNone(result["pending_action"])
        self.assertIsNotNone(result["review_case"])
        self.assertEqual(result["stop_reason"], "ineligible_action_case_saved")

    def test_refund_and_outside_window_case_then_followup(self):
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)
        statement = "I want a refund for order-1005"

        def proposal(state):
            order = next(
                item
                for entry in state["observations"]
                for item in entry["results"]
                if item.get("kind") == "order"
            )
            return ModelTurn(
                decision="Request human refund review",
                proposal=CaseRequest(
                    kind="create_case",
                    category=CaseCategory.REFUND,
                    order_id="order-1005",
                    customer_statement=statement,
                    evidence_ids=(order["evidence_id"],),
                ),
            )

        self.model.script = [tool("order_detail", order_id="order-1005"), proposal]
        result = self.send(statement)
        case = result["review_case"]
        self.assertEqual(result["task"]["kind"], "human_review")
        self.assertEqual(result["task"]["case_ids"], [case["case_id"]])
        self.assertEqual(case["status"], "pending_review")
        self.assertEqual(case["category"], "refund_review")
        self.assertEqual(case["human_decision"], "not_decided")
        self.assertTrue(case["case_id"].startswith("case-"))
        self.assertIsNone(result["receipt"])
        self.runtime.judge = FakeJudge()
        self.model.script = [
            tool("case_detail", record_id=case["case_id"]),
            answer("Your case is pending review; a human has not decided it."),
        ]
        followup = self.send("What is the status of that case?")
        self.assertEqual(followup["disposition"], "answered")
        self.assertEqual(followup["task"]["task_id"], result["task"]["task_id"])
        self.assertIn(case["case_id"], self.model.calls[-2]["case_ids"])

    def test_human_handoff_and_case_scope(self):
        self.runtime.judge = FakeJudge(intent=Intent.HUMAN)
        self.model.script = []
        result = self.send("I want a human")
        self.assertEqual(result["disposition"], "case_created")
        self.assertEqual(result["review_case"]["category"], "general_support")
        foreign = self.client.post(
            self.base + "/sessions", json={"customer_id": "customer-sam"}
        ).json()["token"]
        headers = {"Authorization": "Bearer " + foreign}
        url = (
            self.base
            + f"/conversations/{self.conversation}/cases/{result['review_case']['case_id']}"
        )
        self.assertEqual(self.client.get(url, headers=headers).status_code, 404)
        self.assertEqual(
            self.client.get(url, headers=self.headers).json()["status"],
            "pending_review",
        )

    def test_foreign_confirmation_and_unknown_order(self):
        result = self.propose()
        sam = self.client.post(
            self.base + "/sessions", json={"customer_id": "customer-sam"}
        ).json()["token"]
        self.assertEqual(
            self.decide(result, headers={"Authorization": "Bearer " + sam}).status_code,
            404,
        )
        result = self.propose(order="order-2001")
        self.assertEqual(result["disposition"], "handoff_needed")
        self.assertIsNone(result["review_case"])
        self.assertIsNone(result["pending_action"])

    def test_yes_does_not_execute(self):
        self.propose()
        self.model.script = []
        followup = self.send("Do it for me")
        self.assertEqual(followup["stop_reason"], "explicit_confirmation_required")
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "paid",
        )

    def test_receipt_failure_rolls_back_order_and_proposal(self):
        result = self.propose()

        def fail(mapper, connection, target):
            raise RuntimeError("receipt persistence failed")

        event.listen(SupportReceipt, "before_insert", fail)
        try:
            with self.assertRaises(RuntimeError):
                confirm(
                    self.repo,
                    UUID(self.token),
                    UUID(self.conversation),
                    UUID(result["pending_action"]["proposal_id"]),
                    ConfirmationRequest(decision="confirm"),
                    self.store,
                )
        finally:
            event.remove(SupportReceipt, "before_insert", fail)
        with Session(self.engine) as db:
            self.assertEqual(require_row(db, SupportOrder, "order-1001").version, 1)
            self.assertEqual(
                require_row(
                    db, SupportProposal, UUID(result["pending_action"]["proposal_id"])
                ).state,
                "pending",
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportReceipt)), 0
            )
        self.assertEqual(self.decide(result).json()["receipt"]["outcome"], "executed")

    def test_case_replay_does_not_create_another_case(self):
        self.runtime.judge = FakeJudge(intent=Intent.HUMAN)
        self.model.script = []
        result = self.send("Please let me speak to a human")
        replay = self.client.post(
            self.base
            + f"/conversations/{self.conversation}/runs/{result['run_id']}/replay",
            headers=self.headers,
        )
        self.assertEqual(replay.json(), result)
        with Session(self.engine) as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportCase)), 1
            )
            case = next(iter(db.scalars(select(SupportCase))))
            self.assertFalse(case.payload["customer_statements_are_verified"])

    def test_case_output_failure_rolls_back_and_releases_reservation(self):
        self.runtime.judge = FakeJudge(intent=Intent.HUMAN)
        self.model.script = []

        def fail(mapper, connection, target):
            raise RuntimeError("output persistence failed")

        event.listen(SupportOutput, "before_insert", fail)
        try:
            with self.assertRaises(RuntimeError):
                self.send("Please let me speak to a human")
        finally:
            event.remove(SupportOutput, "before_insert", fail)
        with Session(self.engine) as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportCase)), 0
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportOutput)), 0
            )
            conversation = require_row(db, SupportConversation, UUID(self.conversation))
            self.assertIsNone(conversation.active_run_id)
            self.assertEqual(next(iter(db.scalars(select(LlmRun)))).status, "failed")

    def test_proposal_grounding_and_invented_address_block(self):
        self.runtime.judge = FakeJudge(intent=Intent.ACTION, grounding=0.2)

        def rejected_proposal(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            order = next(item for item in evidence if item["kind"] == "order")
            policy = next(item for item in evidence if item["kind"] == "policy")
            return ModelTurn(
                decision="Propose",
                proposal=CancelProposal(
                    kind="cancel_order",
                    order_id="order-1001",
                    evidence_ids=(policy["evidence_id"], order["evidence_id"]),
                ),
            )

        self.model.script = [
            tool("policy_search", query="cancellation"),
            tool("order_detail", order_id="order-1001"),
            rejected_proposal,
        ]
        response = self.send("Cancel order-1001")
        self.assertEqual(response["disposition"], "clarification")
        self.assertIsNone(response["pending_action"])
        self.assertEqual(response["stop_reason"], "proposal_grounding_rejected")
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)
        address = Address(
            line1="999 Invented Lane",
            city="Inventedville",
            postal_code="99999",
            country="US",
        )

        def invalid(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            order = next(item for item in evidence if item["kind"] == "order")
            policy = next(item for item in evidence if item["kind"] == "policy")
            return ModelTurn(
                decision="Propose",
                proposal=AddressProposal(
                    kind="change_address",
                    order_id="order-1001",
                    address=address,
                    evidence_ids=(policy["evidence_id"], order["evidence_id"]),
                ),
            )

        self.model.script = [
            tool("policy_search", query="address change"),
            tool("order_detail", order_id="order-1001"),
            invalid,
        ]
        response = self.send("Change the address for order-1001")
        self.assertEqual(response["stop_reason"], "invented_address")

    def test_concurrent_confirmations_apply_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Barrier

        from sqlalchemy import create_engine

        from backend.customer_support.repository import SupportRepository

        result = self.propose()
        models = (
            LlmRun,
            SupportDemoSession,
            SupportConversation,
            SupportOutput,
            SupportOrder,
            SupportProposal,
            SupportCase,
            SupportReceipt,
            SupportTask,
        )
        with TemporaryDirectory() as directory:
            engine = create_engine(
                "sqlite+pysqlite:///" + str(Path(directory) / "race.sqlite"),
                connect_args={"check_same_thread": False, "timeout": 5},
            )
            Base.metadata.create_all(
                engine,
                tables=[Base.metadata.tables[model.__tablename__] for model in models],
            )
            with Session(self.engine) as source, Session(engine) as target:
                for model in models:
                    for row in source.scalars(select(model)):
                        target.add(
                            model(
                                **{
                                    column.name: getattr(row, column.name)
                                    for column in Base.metadata.tables[
                                        model.__tablename__
                                    ].columns
                                }
                            )
                        )
                    target.flush()
                target.commit()

            @contextmanager
            def sessions():
                with Session(engine) as db:
                    try:
                        yield db
                        db.commit()
                    except BaseException:
                        db.rollback()
                        raise

            repo = SupportRepository(sessions)
            barrier = Barrier(2)

            def attempt():
                barrier.wait(timeout=3)
                try:
                    return confirm(
                        repo,
                        UUID(self.token),
                        UUID(self.conversation),
                        UUID(result["pending_action"]["proposal_id"]),
                        ConfirmationRequest(decision="confirm"),
                        self.store,
                    ).receipt
                except ValueError:
                    return None  # The losing transaction may require replay after the winner commits.

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(attempt)
                    second = pool.submit(attempt)
                    self.assertTrue(
                        any(
                            receipt is not None
                            for receipt in (first.result(), second.result())
                        )
                    )
                with Session(engine) as db:
                    self.assertEqual(
                        db.scalar(select(func.count()).select_from(SupportReceipt)), 1
                    )
                    self.assertEqual(
                        require_row(db, SupportOrder, "order-1001").version, 2
                    )
            finally:
                engine.dispose()

    def test_no_refund_executor_schema(self):
        from pydantic import TypeAdapter

        from backend.customer_support.contracts import OperationProposal

        with self.assertRaises(ValidationError):
            TypeAdapter(OperationProposal).validate_python(
                {"kind": "execute_refund", "order_id": "order-1001"}
            )


if __name__ == "__main__":
    unittest.main()
