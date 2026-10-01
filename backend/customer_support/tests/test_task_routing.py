"""Offline continuation decisions: context selection never authorizes an action."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.customer_support.contracts import (
    ConversationTurn,
    MessageRequest,
    TaskCheckpoint,
    TaskRoute,
)
from backend.customer_support.providers import LiveJevJudge
from backend.customer_support.task_routing import route_message
from backend.customer_support.tests.test_workflow import FakeJudge


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cancel = TaskCheckpoint(
            task_id="cancel-task",
            goal="Cancel the R50",
            status="awaiting_clarification",
        )
        self.address = TaskCheckpoint(
            task_id="address-task",
            kind="change_address",
            goal="Change my shipping address",
            status="awaiting_clarification",
        )
        self.judge = FakeJudge()

    async def route(self, text, tasks=None, history=None, task_id=None):
        return await route_message(
            MessageRequest(message=text, task_id=task_id),
            history or [],
            tasks or [],
            self.judge,
        )

    async def test_new_topic_keeps_old_task_and_policy_question_has_no_task(self):
        result, _, source = await self.route(
            "Change my shipping address", [self.cancel]
        )
        self.assertEqual(result.task_kind, "change_address")
        self.assertEqual(source, "new_topic")
        result, _, _ = await self.route("What is your return policy?", [self.cancel])
        self.assertEqual(result.route, "new")
        self.assertIsNone(result.task_kind)
        self.assertEqual(self.judge.calls, [])

    async def test_ambiguous_targets_clarify_instead_of_selecting_latest(self):
        result, _, source = await self.route("That one", [self.cancel, self.address])
        self.assertEqual(result.route, "clarify")
        self.assertEqual(source, "jev_continuation")

    async def test_jev_can_select_an_older_task(self):
        self.judge.route_decision = TaskRoute(
            route="resume", task_id=self.cancel.task_id, probability=0.95
        )
        result, _, _ = await self.route(
            "Back to that earlier request", [self.address, self.cancel]
        )
        self.assertEqual(result.task_id, self.cancel.task_id)

    async def test_low_confidence_or_foreign_task_is_not_used(self):
        self.judge.route_decision = TaskRoute(
            route="resume", task_id=self.cancel.task_id, probability=0.5
        )
        result, _, _ = await self.route("That one", [self.cancel])
        self.assertEqual(result.route, "clarify")
        self.judge.route_decision = TaskRoute(route="resume", task_id="foreign-task")
        with self.assertRaises(ValueError):
            await self.route("That one", [self.cancel])
        with self.assertRaises(LookupError):
            await self.route("Status please", [self.cancel], task_id="foreign-task")

    async def test_explicit_task_skips_jev_and_abandonment_uses_current_context(self):
        result, _, _ = await self.route(
            "Status please", [self.cancel, self.address], task_id=self.cancel.task_id
        )
        self.assertEqual(result.task_id, self.cancel.task_id)
        history = [
            ConversationTurn(
                question="Cancel it", answer="Which order?", task_id=self.cancel.task_id
            )
        ]
        result, _, _ = await self.route("Never mind", [self.cancel], history)
        self.assertEqual(result.route, "abandon")
        self.assertEqual(self.judge.calls, [])

    async def test_prechecks_precede_semantic_routing_and_invalid_input_stops(self):
        order = []
        self.judge.route_decision = TaskRoute(
            route="correct", task_id=self.cancel.task_id
        )
        await route_message(
            MessageRequest(message="Actually, the other one"),
            [],
            [self.cancel],
            self.judge,
            on_precheck=lambda _: order.append("precheck"),
            on_input=lambda _: order.append("input"),
        )
        self.assertEqual(order, ["precheck", "input"])
        with self.assertRaises(ValueError):
            await self.route("???", [self.cancel])
        self.assertEqual(len(self.judge.calls), 1)

    async def test_live_adapter_rejects_close_semantic_tie(self):
        response = SimpleNamespace(
            nouls={
                k: SimpleNamespace(noul=p)
                for k, p in {
                    "new": 0.1,
                    "clarify": 0.1,
                    "resume_0": 0.92,
                    "correct_0": 0.9,
                    "abandon_0": 0.1,
                }.items()
            },
            usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 100}),
        )
        adapter = LiveJevJudge()
        with patch.object(adapter, "_ask", AsyncMock(return_value=response)):
            result = await adapter.route_task(
                {"tasks": [self.cancel.model_dump(mode="json")]}
            )
        self.assertEqual(result.route, "clarify")
        self.assertIsNone(result.task_id)

    async def test_action_followups_resume_current_pending_task_without_jev(self):
        from backend.customer_support.service import is_confirmation_reply

        task = self.cancel.model_copy(update={"status": "awaiting_approval"})
        history = [
            ConversationTurn(
                question="Cancel it", answer="Confirmation card", task_id=task.task_id
            )
        ]
        for text in (
            "Do it for me",
            "Please do that",
            "Okay, go ahead",
            "Proceed with it",
            "OK go ahead and cancel it",
        ):
            with self.subTest(text=text):
                result, _, _ = await self.route(text, [task], history)
                self.assertEqual(result.task_id, task.task_id)
                self.assertTrue(is_confirmation_reply(text))
        self.assertEqual(self.judge.calls, [])
        self.assertFalse(is_confirmation_reply("What happens if I do it?"))
        self.assertFalse(is_confirmation_reply("Actually cancel the other one"))
