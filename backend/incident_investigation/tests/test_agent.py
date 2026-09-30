import asyncio
import json
import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"

from backend.db.schemas import LlmRun
from backend.incident_investigation.agent import agent
from backend.incident_investigation.contracts import InvestigationRequest
from backend.incident_investigation.service import run_investigation
from backend.main import app


def at(minute: int) -> str:
    return datetime(2026, 4, 14, 14, minute, tzinfo=timezone.utc).isoformat()


class IncidentAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        LlmRun.__table__.create(self.engine)
        self.request = InvestigationRequest(
            service="checkout",
            alert_id="alert-0001",
            window_start=at(0),
            window_end=at(59),
        )

    def tearDown(self) -> None:
        self.engine.dispose()

    @contextmanager
    def sessions(self):
        with Session(self.engine) as session:
            yield session
            session.commit()

    async def test_streaming_api_runs_fake_model_through_verification(self) -> None:
        async def model_function(messages, info):
            if len(messages) == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "list_changes",
                            {
                                "inputs": {
                                    "service": "payments",
                                    "start": at(0),
                                    "end": at(45),
                                }
                            },
                        )
                    ]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "observations": [
                                {
                                    "statement": "Payments pool configuration changed.",
                                    "kind": "fact",
                                    "evidence_ids": ["changes-0002"],
                                }
                            ],
                            "candidate_causes": [],
                            "unknowns": [],
                            "next_checks": [],
                        },
                    )
                ]
            )

        async def fake_run(request, *, on_step):
            return await run_investigation(
                request,
                session_scope=self.sessions,
                model=FunctionModel(model_function),
                on_step=on_step,
            )

        with patch("backend.incident_investigation.api.run_investigation", fake_run):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/agent/incident_investigation/stream",
                    json=self.request.model_dump(mode="json"),
                )

        self.assertEqual(response.status_code, 200)
        events = []
        for frame in response.text.split("\n\n"):
            if not frame:
                continue
            lines = dict(line.split(": ", 1) for line in frame.splitlines())
            events.append((lines["event"], json.loads(lines["data"])))
        self.assertEqual(events[-1][0], "result")
        result = events[-1][1]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["report"]["timeline"][0]["evidence_ids"], ["changes-0002"]
        )
        self.assertEqual(
            [payload for kind, payload in events if kind == "step"],
            result["workflow_steps"],
        )
        tool_result = next(
            payload
            for kind, payload in events
            if kind == "step" and payload["stage"] == "tool"
        )
        self.assertEqual(
            tool_result["details"]["result"]["records"][0]["evidence_id"],
            "changes-0002",
        )

    async def test_mock_model_follows_cross_service_evidence_and_records_steps(
        self,
    ) -> None:
        decisions = [
            (
                "get_metric_series",
                {
                    "inputs": {
                        "service": "payments",
                        "metric": "db_connection_wait_ms",
                        "start": at(10),
                        "end": at(45),
                    }
                },
            ),
            (
                "get_metric_series",
                {
                    "inputs": {
                        "service": "checkout",
                        "metric": "error_rate",
                        "start": at(10),
                        "end": at(45),
                    }
                },
            ),
            (
                "list_changes",
                {
                    "inputs": {
                        "service": "payments",
                        "start": at(0),
                        "end": at(45),
                    }
                },
            ),
            ("inspect_trace", {"inputs": {"trace_id": "trace-0028"}}),
        ]
        tool_results: list[dict] = []

        async def model_function(messages, info):
            latest = messages[-1]
            for part in latest.parts:
                if isinstance(part, ToolReturnPart):
                    content = part.content
                    tool_results.append(
                        json.loads(content) if isinstance(content, str) else content
                    )
            if len(tool_results) < len(decisions):
                if len(tool_results) == 1:
                    self.assertGreater(
                        max(point["value"] for point in tool_results[0]["records"]),
                        2000,
                    )
                if len(tool_results) == 2:
                    self.assertGreater(
                        max(point["value"] for point in tool_results[1]["records"]),
                        0.10,
                    )
                name, args = decisions[len(tool_results)]
                return ModelResponse(parts=[ToolCallPart(name, args)])
            evidence_ids = [
                max(tool_results[0]["records"], key=lambda point: point["value"])[
                    "evidence_id"
                ],
                max(tool_results[1]["records"], key=lambda point: point["value"])[
                    "evidence_id"
                ],
            ]
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "observations": [
                                {
                                    "statement": "Payments connection waits rose during the checkout error window.",
                                    "kind": "correlation",
                                    "evidence_ids": evidence_ids[:2],
                                }
                            ],
                            "candidate_causes": [],
                            "unknowns": [
                                "Payments trace spans are sampled out for part of the window."
                            ],
                            "next_checks": [
                                "Confirm the pool setting with the payments owner."
                            ],
                        },
                    )
                ]
            )

        streamed_steps = []
        outcome = await run_investigation(
            self.request,
            session_scope=self.sessions,
            model=FunctionModel(model_function),
            on_step=streamed_steps.append,
        )
        self.assertEqual(
            outcome.status,
            "completed",
            msg=f"{outcome.error_type}: {outcome.tool_steps}",
        )
        self.assertEqual(outcome.stop_reason, "completed")
        self.assertEqual(len(outcome.tool_steps), 4)
        self.assertEqual(streamed_steps, outcome.workflow_steps)
        self.assertEqual(
            [step.stage for step in outcome.workflow_steps[:5]],
            ["guardrail", "scope", "registry", "registry", "agent"],
        )
        self.assertEqual(
            [step.stage for step in outcome.workflow_steps[5:13]],
            ["agent", "tool"] * 4,
        )
        self.assertEqual(
            [step.stage for step in outcome.workflow_steps[-3:]],
            ["agent", "verification", "registry"],
        )
        self.assertEqual(
            outcome.workflow_steps[6].details["result"]["records"],
            tool_results[0]["records"],
        )
        self.assertEqual(outcome.workflow_steps[-1].details["status"], "completed")
        self.assertEqual(outcome.tool_steps[-1].coverage_gaps[0].service, "payments")
        self.assertGreater(len(outcome.surfaced_evidence_ids), 5)
        self.assertLessEqual(len(tool_results[0]["records"]), 12)
        self.assertGreater(tool_results[0]["total_returned_by_query"], 12)
        self.assertTrue(tool_results[0]["condensed"])
        self.assertTrue(outcome.tool_steps[0].condensed)
        selected_times = {point["observed_at"] for point in tool_results[0]["records"]}
        self.assertIn("2026-04-14T14:15:00Z", selected_times)
        self.assertIn("2026-04-14T14:42:00Z", selected_times)
        self.assertIsNotNone(outcome.draft)
        self.assertTrue(outcome.verification.passed)
        self.assertTrue(outcome.report.review_required)
        self.assertEqual(len(outcome.report.timeline), 1)
        self.assertEqual(outcome.report.timeline[0].kind, "correlation")
        self.assertEqual(outcome.report.coverage_gaps[0].service, "payments")
        self.assertIsNone(outcome.logfire_trace_id)
        self.assertIn(
            outcome.draft.observations[0].evidence_ids[0],
            outcome.surfaced_evidence_ids,
        )
        with Session(self.engine) as session:
            run = session.get(LlmRun, outcome.run_id)
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.system_key, "incident_investigation")
            self.assertEqual(run.logfire_trace_id, outcome.logfire_trace_id)

    async def test_out_of_scope_tool_call_is_recorded_as_blocked(self) -> None:
        calls = 0

        async def model_function(messages, info):
            nonlocal calls
            calls += 1
            if calls == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "search_logs",
                            {
                                "inputs": {
                                    "service": "email-worker",
                                    "start": at(0),
                                    "end": at(20),
                                }
                            },
                        )
                    ]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "observations": [],
                            "candidate_causes": [],
                            "unknowns": [],
                            "next_checks": [],
                        },
                    )
                ]
            )

        outcome = await run_investigation(
            self.request,
            session_scope=self.sessions,
            model=FunctionModel(model_function),
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.stop_reason, "verification_failed")
        self.assertEqual(outcome.verification.issues[0].code, "empty_report")
        self.assertIsNone(outcome.report)
        self.assertEqual(outcome.tool_steps[0].returned_evidence_ids, [])
        self.assertIn("outside investigation scope", outcome.tool_steps[0].error)

    async def test_timeout_marks_run_failed(self) -> None:
        async def slow_model(messages, info):
            await asyncio.sleep(0.05)
            return ModelResponse(parts=[])

        outcome = await run_investigation(
            self.request,
            session_scope=self.sessions,
            model=FunctionModel(slow_model),
            timeout_seconds=0.005,
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.stop_reason, "timeout")
        self.assertEqual(outcome.workflow_steps[-2].details["stop_reason"], "timeout")
        self.assertIsNone(outcome.draft)
        with Session(self.engine) as session:
            self.assertEqual(session.get(LlmRun, outcome.run_id).status, "failed")

    async def test_tool_budget_exhaustion_marks_run_failed(self) -> None:
        async def repeated_query(messages, info):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "list_changes",
                        {
                            "inputs": {
                                "service": "payments",
                                "start": at(0),
                                "end": at(45),
                            }
                        },
                    )
                ]
            )

        outcome = await run_investigation(
            self.request,
            session_scope=self.sessions,
            model=FunctionModel(repeated_query),
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.stop_reason, "budget_exhausted")
        self.assertLessEqual(len(outcome.tool_steps), 9)
        self.assertEqual(agent.model_settings["parallel_tool_calls"], False)
        failure = next(
            step
            for step in outcome.workflow_steps
            if step.stage == "agent" and step.status == "failed"
        )
        self.assertIn("limit", failure.details["failure_detail"])
        self.assertGreater(failure.details["usage"]["tool_calls"], 0)
        with Session(self.engine) as session:
            self.assertEqual(session.get(LlmRun, outcome.run_id).status, "failed")

    async def test_model_failure_marks_run_failed(self) -> None:
        async def broken_model(messages, info):
            raise RuntimeError("synthetic model failure")

        outcome = await run_investigation(
            self.request,
            session_scope=self.sessions,
            model=FunctionModel(broken_model),
        )
        self.assertEqual(outcome.stop_reason, "agent_error")
        self.assertEqual(outcome.error_type, "RuntimeError")
        with Session(self.engine) as session:
            self.assertEqual(session.get(LlmRun, outcome.run_id).status, "failed")


if __name__ == "__main__":
    unittest.main()
