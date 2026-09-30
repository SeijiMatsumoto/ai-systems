import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from backend.research_workflow.agent.jev_classifier import (
    classify_research_query,
    decide_query_gate,
)
from backend.research_workflow.contracts import ResearchQueryJevJudgment


class FakeClient:
    def __init__(self, **kwargs):
        self.call = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def system_one(self, **kwargs):
        self.call = kwargs
        return SimpleNamespace(
            model="jev-test",
            nouls={
                "company_relevance": SimpleNamespace(noul=0.91),
                "instruction_attempt": SimpleNamespace(noul=0.03),
            },
            usage=SimpleNamespace(
                model_dump=lambda: {"input_tokens": 82, "output_tokens": 3}
            ),
        )


class FakeSpan:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def set_attribute(self, *_args):
        pass


class JevResearchGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_sends_two_typed_questions_and_reports_usage(self) -> None:
        client = FakeClient()
        with (
            patch(
                "backend.research_workflow.agent.jev_classifier.AsyncTypeSafeClient",
                return_value=client,
            ),
            patch(
                "backend.research_workflow.agent.jev_classifier.logfire.span",
                return_value=FakeSpan(),
            ),
        ):
            judgment = await classify_research_query(
                "aapl", "What risks does Apple face?"
            )
        self.assertEqual(client.call["model"], "jev-latest")
        self.assertEqual(client.call["state"]["symbol"], "AAPL")
        self.assertEqual(
            set(client.call["questions"]), {"company_relevance", "instruction_attempt"}
        )
        self.assertTrue(
            all(
                question.type == "noul"
                for question in client.call["questions"].values()
            )
        )
        self.assertEqual(judgment.usage["input_tokens"], 82)
        self.assertEqual(decide_query_gate(judgment).outcome, "accept")

    async def test_gate_accept_reject_and_fallback_bands(self) -> None:
        cases = [
            (0.8, 0.2, "accept"),
            (0.2, 0.1, "reject"),
            (0.9, 0.8, "reject"),
            (0.6, 0.1, "fallback"),
            (0.9, 0.4, "fallback"),
        ]
        for relevant, instruction, expected in cases:
            judgment = ResearchQueryJevJudgment(
                model="fake",
                question_version=1,
                relevance_probability=relevant,
                instruction_probability=instruction,
                usage={},
            )
            self.assertEqual(decide_query_gate(judgment).outcome, expected)
        with self.assertRaises(ValidationError):
            ResearchQueryJevJudgment(
                model="fake",
                question_version=1,
                relevance_probability=float("nan"),
                instruction_probability=0.1,
                usage={},
            )


if __name__ == "__main__":
    unittest.main()
