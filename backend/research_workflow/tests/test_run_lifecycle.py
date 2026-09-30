import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.schemas import LlmRun, ResearchRun, ResearchRunStatus, ResearchRunStep
from backend.research_workflow.api import get_research_run_detail
from backend.research_workflow.contracts import (
    BriefingNarrative,
    BriefingRequest,
    DraftFinding,
    DraftResearchBriefing,
    GroundingClassification,
    QueryClassification,
    ResearchQueryJevJudgment,
)
from backend.research_workflow.service import research
from backend.research_workflow.service.run_record import saved_steps


@dataclass
class FakeUsage:
    requests: int = 3
    input_tokens: int = 140
    output_tokens: int = 70


class ResearchRunLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'runs.db'}")
        LlmRun.__table__.create(self.engine)
        ResearchRun.__table__.create(self.engine)
        ResearchRunStep.__table__.create(self.engine)

        @contextmanager
        def get_session():
            with Session(self.engine, expire_on_commit=False) as session:
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

        self.get_session = get_session
        self.patch_session = patch.object(research.db_utils, "get_session", get_session)
        self.patch_session.start()
        self.addCleanup(self.patch_session.stop)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.temp.cleanup)
        self.as_of = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.request = BriefingRequest(
            symbol="AAPL",
            as_of=self.as_of,
            research_question="What changed in Apple's recent share price trend?",
            audience="investors",
            time_horizon="12m",
        )

    async def test_failed_checkpoint_resumes_as_new_shared_run_with_ordered_steps(
        self,
    ) -> None:
        seen_steps = []
        agent_calls = []

        async def classify(symbol, question, run_id, *, on_usage):
            on_usage("query_classifier", {"requests": 1, "input_tokens": 20})
            return QueryClassification(is_relevant=True, reasoning="Company research")

        async def jev(symbol, question):
            return ResearchQueryJevJudgment(
                model="fake-jev",
                question_version=1,
                relevance_probability=0.5,
                instruction_probability=0.1,
                usage={"input_tokens": 100, "output_tokens": 2},
            )

        async def agent(**kwargs):
            agent_calls.append(kwargs["run_id"])
            kwargs["on_event"](
                "tool",
                "running",
                "search_web called",
                {"arguments": {"query": "Apple pricing update", "limit": 3}},
            )
            kwargs["on_event"](
                "tool",
                "completed",
                "search_web returned",
                {
                    "result": {
                        "results": [{"result_id": "tavily:one"}],
                        "provider_usage": {"credits": 1},
                    }
                },
            )
            kwargs["on_event"](
                "tool",
                "running",
                "inspect_web_results called",
                {"arguments": {"result_ids": ["tavily:one"], "focus": "pricing"}},
            )
            kwargs["on_event"](
                "tool",
                "completed",
                "inspect_web_results returned",
                {
                    "result": {
                        "evidence_candidates": [],
                        "provider_usage": {"credits": 2},
                    }
                },
            )
            evidence_id = next(iter(kwargs["evidence_catalog"]))
            draft = DraftResearchBriefing(
                executive_summary="Price movement observed.",
                key_findings=[
                    DraftFinding(
                        statement="The price changed.",
                        claim_type="fact",
                        confidence=2,
                        evidence_ids=[evidence_id],
                    )
                ],
                outlook="Monitor the next close.",
            )
            return SimpleNamespace(
                result=SimpleNamespace(output=draft, usage=FakeUsage()),
                evidence_catalog=kwargs["evidence_catalog"],
                financial_sources=kwargs["financial_sources"],
            )

        async def unsupported(*args, **kwargs):
            return GroundingClassification(is_supported=False, reasoning="Needs review")

        async def repair_fails(*args, **kwargs):
            raise RuntimeError("repair unavailable")

        async def supported(*args, **kwargs):
            kwargs["on_usage"](
                "grounding_classifier", {"requests": 1, "input_tokens": 40}
            )
            return GroundingClassification(is_supported=True, reasoning="Exact value")

        async def narrative(*args, **kwargs):
            kwargs["on_usage"]("narrative", {"requests": 1, "input_tokens": 30})
            return BriefingNarrative(
                executive_summary="The price changed.", outlook="Watch the price."
            )

        close_data = [
            {
                "Date": (self.as_of - timedelta(days=2)).date().isoformat(),
                "Close": 100.0,
            },
            {
                "Date": (self.as_of - timedelta(days=1)).date().isoformat(),
                "Close": 110.0,
            },
        ]
        with (
            patch.object(research, "run_query_classifier", classify),
            patch.object(research, "classify_research_query", jev),
            patch.object(research, "run_research_briefing_agent", agent),
            patch.object(
                research,
                "get_company_snapshot",
                return_value={"symbol": "AAPL", "company_name": "Apple Inc."},
            ),
            patch.object(research, "get_close_data", return_value=close_data),
            patch.object(research, "verify_finding", unsupported),
            patch.object(research, "revise_finding", repair_fails),
            self.assertRaisesRegex(RuntimeError, "No grounded findings"),
        ):
            await research.run_research_workflow(
                self.request, on_step=seen_steps.append
            )

        with self.get_session() as session:
            failed = session.query(ResearchRun).one()
            failed_id = failed.id
            self.assertEqual(failed.status, ResearchRunStatus.FAILED)
            self.assertEqual(
                failed.checkpoint_stage, research.AGENT_COMPLETED_CHECKPOINT
            )
            self.assertEqual(session.get(LlmRun, failed_id).status, "failed")

        with (
            patch.object(research, "run_research_briefing_agent", agent),
            patch.object(research, "verify_finding", supported),
            patch.object(research, "synthesize_narrative", narrative),
        ):
            result = await research.run_research_workflow(
                self.request, on_step=seen_steps.append
            )
            cached = await research.run_research_workflow(self.request)

        self.assertEqual(result.status, ResearchRunStatus.COMPLETED)
        self.assertEqual(cached.run_id, result.run_id)
        self.assertEqual(len(agent_calls), 1)
        self.assertNotEqual(result.run_id, failed_id)
        with self.get_session() as session:
            old = session.get(ResearchRun, failed_id)
            resumed = session.get(ResearchRun, result.run_id)
            self.assertEqual(old.status, ResearchRunStatus.FAILED)
            self.assertEqual(resumed.resumed_from_run_id, failed_id)
            self.assertEqual(resumed.status, ResearchRunStatus.COMPLETED)
            self.assertEqual(session.get(LlmRun, result.run_id).status, "completed")
            self.assertGreaterEqual(len(resumed.usage_payload["calls"]), 3)

        old_steps = saved_steps(failed_id)
        new_steps = saved_steps(result.run_id)
        self.assertEqual(
            [step.sequence for step in old_steps], list(range(1, len(old_steps) + 1))
        )
        self.assertEqual(
            [step.sequence for step in new_steps], list(range(1, len(new_steps) + 1))
        )
        self.assertEqual(old_steps[-1].status, "failed")
        self.assertEqual(new_steps[-1].details["stop_reason"], "verified_briefing")
        self.assertEqual(len(seen_steps), len(old_steps) + len(new_steps))
        tool_steps = [step for step in old_steps if step.stage == "tool"]
        self.assertEqual(len(tool_steps), 4)
        self.assertEqual(
            tool_steps[1].details["result"]["provider_usage"]["credits"], 1
        )
        self.assertEqual(
            tool_steps[3].details["result"]["provider_usage"]["credits"], 2
        )
        detail = get_research_run_detail(result.run_id)
        self.assertEqual(detail["resumed_from_run_id"], failed_id)
        self.assertEqual(len(detail["workflow_steps"]), len(new_steps))

    async def test_jev_rejection_stops_before_provider_prefetch(self) -> None:
        async def reject(symbol, question):
            return ResearchQueryJevJudgment(
                model="fake-jev",
                question_version=1,
                relevance_probability=0.1,
                instruction_probability=0.01,
                usage={"input_tokens": 20},
            )

        with (
            patch.object(research, "classify_research_query", reject),
            patch.object(research, "run_query_classifier") as fallback,
            patch.object(research, "get_company_snapshot") as prefetch,
            self.assertRaisesRegex(ValueError, "not relevant"),
        ):
            await research.run_research_workflow(self.request)
        fallback.assert_not_called()
        prefetch.assert_not_called()
        with self.get_session() as session:
            run = session.query(ResearchRun).one()
            self.assertEqual(run.status, ResearchRunStatus.FAILED)
            self.assertEqual(session.get(LlmRun, run.id).status, "failed")
            steps = saved_steps(run.id)
            self.assertTrue(
                any(step.details.get("outcome") == "reject" for step in steps)
            )

    async def test_jev_unavailable_uses_visible_fallback(self) -> None:
        async def unavailable(symbol, question):
            raise TimeoutError("fake Jev timeout")

        async def fallback(symbol, question, run_id, *, on_usage):
            on_usage("query_classifier", {"requests": 1})
            return QueryClassification(is_relevant=False, reasoning="Unrelated request")

        with (
            patch.object(research, "classify_research_query", unavailable),
            patch.object(research, "run_query_classifier", fallback),
            patch.object(research, "get_company_snapshot") as prefetch,
            self.assertRaisesRegex(ValueError, "not relevant"),
        ):
            await research.run_research_workflow(self.request)
        prefetch.assert_not_called()
        with self.get_session() as session:
            run = session.query(ResearchRun).one()
            steps = saved_steps(run.id)
            self.assertTrue(
                any(
                    step.details.get("fallback_reason") == "jev_unavailable"
                    for step in steps
                )
            )
            self.assertEqual(
                run.usage_payload["calls"][0]["component"], "query_classifier"
            )


if __name__ == "__main__":
    unittest.main()
