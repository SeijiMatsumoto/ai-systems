"""Offline evidence freshness and persisted resource accounting boundaries."""

import unittest
from datetime import timedelta

from backend.customer_support.contracts import (
    Evidence,
    SavedPolicyEvidence,
    SupportStep,
    TaskResources,
)
from backend.customer_support.store import MockStore
from backend.customer_support.task_resources import (
    policy_reuse,
    reported_tokens,
    resource_totals,
)


class ResourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = MockStore.load()
        passage = self.store.fixture.policies[0]
        self.saved = SavedPolicyEvidence(
            source_run_id="prior-run",
            evidence=Evidence(
                evidence_id="S1",
                kind="policy",
                source_id=passage.policy_id,
                locator=f"{passage.revision}:{passage.locator}",
                text=passage.text,
            ),
        )

    def test_only_exact_effective_policy_is_reusable(self):
        accepted, rejected = policy_reuse([self.saved], self.store)
        self.assertEqual(accepted, [self.saved])
        self.assertEqual(rejected, [])
        for changes in (
            {"text": "invented text"},
            {"locator": "old-revision:missing"},
            {"source_id": "different-policy"},
        ):
            item = self.saved.model_copy(
                update={"evidence": self.saved.evidence.model_copy(update=changes)}
            )
            self.assertEqual(policy_reuse([item], self.store)[0], [])
        self.store.fixture = self.store.fixture.model_copy(
            update={
                "scenario_date": self.store.fixture.policies[0].effective_on
                - timedelta(days=1)
            }
        )
        self.assertEqual(policy_reuse([self.saved], self.store)[0], [])

    def test_order_evidence_cannot_enter_reusable_cache(self):
        with self.assertRaises(ValueError):
            SavedPolicyEvidence(
                source_run_id="run",
                evidence=self.saved.evidence.model_copy(update={"kind": "order"}),
            )

    def test_usage_accumulates_provider_tokens_and_exact_tool_requests(self):
        usage = {
            "model": {"input_tokens": 100, "output_tokens": 20},
            "jev": {"input_tokens": 40, "output_tokens": 2},
        }
        self.assertEqual(reported_tokens(usage), 162)
        result = resource_totals(
            TaskResources(executions=2, tokens=400, tool_calls=3),
            usage,
            [
                SupportStep(sequence=1, stage="tool_request"),
                SupportStep(sequence=2, stage="policy_reuse_check"),
            ],
        )
        self.assertEqual(result, TaskResources(executions=3, tokens=562, tool_calls=4))

    async def test_token_and_tool_limits_stop_next_work_independently(self):
        from backend.customer_support.contracts import SupportRequest, TaskCheckpoint
        from backend.customer_support.retrieval import ingest
        from backend.customer_support.service import run_support
        from backend.customer_support.tests.test_workflow import FakeJudge, ScriptModel
        from backend.internal_knowledge_action.embedding import MockEmbeddingProvider

        embedder = MockEmbeddingProvider()
        index = ingest(self.store, embedder)
        for resources, expected_calls in (
            (TaskResources(tokens=60000), 0),
            (TaskResources(tokens=59999), 1),
            (TaskResources(tool_calls=24), 1),
        ):
            with self.subTest(resources=resources):
                model, judge = ScriptModel([]), FakeJudge()
                checkpoint = TaskCheckpoint(
                    task_id="task",
                    goal="Cancel my order",
                    selected_order_ids=("order-1001",),
                    resources=resources,
                )
                result = await run_support(
                    SupportRequest(
                        conversation_id="chat", message="Can I cancel my order?"
                    ),
                    self.store,
                    self.store.sign_in("customer-alex"),
                    model,
                    judge,
                    index,
                    embedder,
                    "run",
                    task_checkpoint=checkpoint,
                    task_resumed=True,
                )
                self.assertEqual(result.disposition, "handoff_needed")
                self.assertIn(
                    result.stop_reason,
                    {"task_resource_budget", "context_or_token_budget"},
                )
                self.assertEqual(model.calls, [])
                self.assertEqual(len(judge.calls), expected_calls)
                self.assertFalse(
                    any(step.stage == "tool_request" for step in result.steps)
                )
