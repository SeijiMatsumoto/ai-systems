"""Offline scoring and adapter checks, not evidence of live classification quality."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.customer_support.contracts import Intent, IntentJudgment
from backend.customer_support.evals.jev import evaluate, load_cases
from backend.customer_support.intent_policy import intent_branch
from backend.customer_support.providers import LiveJevJudge


class EvalTests(unittest.IsolatedAsyncioTestCase):
    def test_dataset_has_separate_holdout_and_contextual_pairs(self):
        cases = load_cases()
        self.assertEqual(len(cases), 36)
        self.assertEqual(sum(case.split == "holdout" for case in cases), 12)
        pairs = [case for case in cases if case.message == "The second one"]
        self.assertEqual(
            {case.expected.intent for case in pairs},
            {Intent.ACTION, Intent.INFORMATION},
        )

    def test_classifier_projects_current_turn_and_reference_context(self):
        from backend.customer_support.intent_classification import classification_input

        result = classification_input(
            {
                "message": " How much did I pay for that? ",
                "signals": ["order"],
                "conversation_context": {
                    "subjects": [{"kind": "order", "record_id": "order-1001"}],
                    "pending": None,
                    "saved_policy": [{"text": "Refund approval"}],
                },
                "available_tasks": [{"goal": "Cancel my order"}],
                "tools": {"cancel": "executor"},
                "recent_turns": [
                    {
                        "question": "Cancel it?",
                        "answer": "Please review the proposal",
                        "task_id": "task-secret",
                    }
                ],
            }
        )
        self.assertEqual(result["message"], "How much did I pay for that?")
        self.assertEqual(result["subjects"][0]["record_id"], "order-1001")
        self.assertEqual(
            set(result), {"message", "recent_turns", "subjects", "pending", "signals"}
        )
        self.assertNotIn("task_id", result["recent_turns"][0])

    async def test_invalid_classifier_input_rejected_before_provider(self):
        judge = LiveJevJudge()
        judge._ask = AsyncMock()
        for message in ("???", "", "x" * 2001):
            with self.assertRaises(ValueError):
                await judge.classify({"message": message})
        judge._ask.assert_not_awaited()

    async def test_categories_share_current_turn_rubric(self):
        from backend.customer_support.intent_classification import INTENT_RUBRIC

        judge = LiveJevJudge()
        scores = {"information": 0.9, "action": 0.1, "human": 0.02, "unsupported": 0.02}
        judge._ask = AsyncMock(
            return_value=SimpleNamespace(
                nouls={
                    key: SimpleNamespace(noul=value) for key, value in scores.items()
                },
                model="fake",
                usage=SimpleNamespace(model_dump=dict),
            )
        )
        await judge.classify(
            {
                "message": "Can I cancel it then?",
                "available_tasks": [{"goal": "Cancel order"}],
            }
        )
        supplied, questions = judge._ask.call_args.args
        self.assertNotIn("available_tasks", supplied)
        self.assertEqual(set(questions), set(scores))
        for question in questions.values():
            self.assertTrue(question.instructions.startswith(INTENT_RUBRIC))

    def test_application_thresholds_are_separate_from_target_resolution(self):
        for intent, probability, gap, expected in [
            (Intent.INFORMATION, 0.51, 0.01, "read_only"),
            (Intent.ACTION, 0.99, 0.01, "read_only"),
            (Intent.ACTION, 0.79, 0.2, "read_only"),
            (Intent.ACTION, 0.95, 0.3, "proposal"),
            (Intent.HUMAN, 0.65, 0.3, "clarify"),
        ]:
            self.assertEqual(
                intent_branch(
                    IntentJudgment(
                        intent=intent,
                        probability=probability,
                        confidence_gap=gap,
                        model="fake",
                    )
                ),
                expected,
            )

    async def test_real_adapter_preserves_scores_and_separation(self):
        judge = LiveJevJudge()
        scores = {
            "information": 0.87,
            "action": 0.85,
            "human": 0.05,
            "unsupported": 0.01,
        }
        judge._ask = AsyncMock(
            return_value=SimpleNamespace(
                nouls={
                    key: SimpleNamespace(noul=value) for key, value in scores.items()
                },
                model="fake",
                usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 19}),
            )
        )
        result = await judge.classify({"message": "fixture"})
        self.assertEqual(result.scores, scores)
        assert result.confidence_gap is not None
        self.assertAlmostEqual(result.confidence_gap, 0.02)
        self.assertEqual(result.usage["total_tokens"], 19)

    async def test_eval_exercises_provider_failure_without_retries(self):
        calls = []

        async def fail(state):
            calls.append(state)
            raise TimeoutError()

        report, observations = await evaluate(load_cases()[:2], fail)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(report.cases), 2)
        self.assertTrue(all(row.error == "TimeoutError" for row in observations))

    async def test_eval_scores_synthetic_predictions_without_quality_claims(self):
        async def classify(state):
            return IntentJudgment(
                intent=Intent.INFORMATION,
                probability=0.9,
                confidence_gap=0.3,
                model="fake",
            )

        report, observations = await evaluate(load_cases()[:2], classify)
        self.assertEqual(len(report.cases), 2)
        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0].judgment.model, "fake")
