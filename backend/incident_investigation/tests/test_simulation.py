import asyncio
import json
import os
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"

from backend.db.schemas import IncidentSimulationOutput, LlmRun
from backend.incident_investigation.classifier import JevJudgment
from backend.incident_investigation.detection import REPLAY_FIXTURE_DIR
from backend.incident_investigation.service import (
    InvestigationExecution,
)
from backend.incident_investigation.service import (
    run_investigation as gated_investigation,
)
from backend.incident_investigation.simulation import run_simulation
from backend.incident_investigation.telemetry import TelemetryStore
from backend.main import app


def at(minute: int) -> str:
    return datetime(2026, 4, 14, 14, minute, tzinfo=timezone.utc).isoformat()


class SimulationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        LlmRun.__table__.create(self.engine)
        IncidentSimulationOutput.__table__.create(self.engine)
        self.store = TelemetryStore(REPLAY_FIXTURE_DIR)
        self.seen_summaries = []

    def tearDown(self) -> None:
        self.engine.dispose()

    @contextmanager
    def sessions(self):
        with Session(self.engine) as session:
            yield session
            session.commit()

    async def classify_labeled(self, summary):
        self.seen_summaries.append(summary)
        probability = 0.9 if "checkout" in summary.services else 0.31
        return JevJudgment(
            model="jev-1.13.0",
            question_version=1,
            probability=probability,
            usage={"input_tokens": 500, "output_tokens": 22},
        )

    async def investigator(self, messages, info):
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "list_changes",
                        {
                            "inputs": {
                                "service": "payments",
                                "start": at(0),
                                "end": at(19),
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
                                "statement": "Payments pool configuration changed before checkout failures.",
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

    async def test_incident_triggers_one_snapshot_scoped_investigation(self) -> None:
        outcome = await run_simulation(
            store=self.store,
            classifier=self.classify_labeled,
            session_scope=self.sessions,
            investigator_model=FunctionModel(self.investigator),
        )
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.stop_reason, "completed")
        self.assertEqual(
            [case.outcome for case in outcome.classifications],
            ["incident", "not_incident"],
        )
        self.assertEqual(outcome.detected_incidents[0].observed_at.minute, 19)
        self.assertEqual(outcome.investigations[0].run_id, outcome.run_id)
        self.assertTrue(
            all(
                (step.summary.endswith("log grouped"))
                == (step.details["log"]["level"] == "ERROR")
                for step in outcome.workflow_steps
                if step.stage == "replay"
            )
        )
        with self.sessions() as session:
            saved = session.get(IncidentSimulationOutput, outcome.run_id)
            self.assertIsNotNone(saved)
            self.assertEqual(saved.response_payload["run_id"], str(outcome.run_id))
            self.assertEqual(
                len(saved.response_payload["workflow_steps"]),
                len(outcome.workflow_steps),
            )
            self.assertEqual(
                saved.response_payload["investigations"][0]["report"]["timeline"][0][
                    "evidence_ids"
                ],
                ["changes-0002"],
            )
        self.assertEqual(
            outcome.investigations[0].report.timeline[0].evidence_ids, ["changes-0002"]
        )
        self.assertEqual(self.seen_summaries[0].latest_error_rates["checkout"], 0.143)
        self.assertNotIn(
            "changes-0003", outcome.investigations[0].surfaced_evidence_ids
        )
        agent_start = next(
            step
            for step in outcome.workflow_steps
            if step.stage == "agent" and "context" in step.details
        )
        self.assertEqual(agent_start.details["context"]["declared_coverage_gaps"], [])
        self.assertTrue(
            all(
                step.sequence == index
                for index, step in enumerate(outcome.workflow_steps, 1)
            )
        )
        self.assertEqual(self.sessions_status(outcome.run_id), "completed")
        with self.sessions() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(LlmRun)), 1
            )

    async def test_full_fixture_run_survives_realistic_sequential_model_usage(
        self,
    ) -> None:
        queries = [
            (
                "search_logs",
                {
                    "service": "checkout",
                    "start": at(0),
                    "end": at(19),
                    "level": "ERROR",
                },
            ),
            (
                "get_metric_series",
                {
                    "service": "checkout",
                    "metric": "error_rate",
                    "start": at(0),
                    "end": at(19),
                },
            ),
            (
                "get_metric_series",
                {
                    "service": "checkout",
                    "metric": "p95_latency_ms",
                    "start": at(0),
                    "end": at(19),
                },
            ),
            (
                "list_changes",
                {"service": "payments", "start": at(0), "end": at(19)},
            ),
            (
                "get_metric_series",
                {
                    "service": "payments",
                    "metric": "db_connection_wait_ms",
                    "start": at(0),
                    "end": at(19),
                },
            ),
            (
                "get_metric_series",
                {
                    "service": "gateway",
                    "metric": "error_rate",
                    "start": at(0),
                    "end": at(19),
                },
            ),
            (
                "get_metric_series",
                {
                    "service": "inventory",
                    "metric": "error_rate",
                    "start": at(0),
                    "end": at(19),
                },
            ),
        ]
        calls = 0

        async def model_function(_messages, info):
            nonlocal calls
            self.assertIs(info.model_settings["parallel_tool_calls"], False)
            usage = RequestUsage(input_tokens=3_500, output_tokens=200)
            if calls < len(queries):
                name, inputs = queries[calls]
                calls += 1
                return ModelResponse(
                    parts=[ToolCallPart(name, {"inputs": inputs})], usage=usage
                )
            calls += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "observations": [
                                {
                                    "statement": "Payments pool configuration changed before checkout errors.",
                                    "kind": "fact",
                                    "evidence_ids": ["changes-0002"],
                                }
                            ],
                            "candidate_causes": [],
                            "unknowns": [],
                            "next_checks": [],
                        },
                    )
                ],
                usage=usage,
            )

        outcome = await run_simulation(
            store=self.store,
            classifier=self.classify_labeled,
            session_scope=self.sessions,
            investigator_model=FunctionModel(model_function),
        )
        investigation = outcome.investigations[0]
        self.assertEqual(calls, 8)
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(len(investigation.tool_steps), 7)
        self.assertGreater(
            investigation.usage["input_tokens"] + investigation.usage["output_tokens"],
            25_000,
        )
        self.assertTrue(investigation.verification.passed)
        self.assertEqual(
            investigation.report.timeline[0].evidence_ids, ["changes-0002"]
        )
        with self.sessions() as session:
            saved = session.get(IncidentSimulationOutput, outcome.run_id)
            self.assertEqual(saved.response_payload["status"], "completed")
            self.assertEqual(
                saved.response_payload["investigations"][0]["report"]["timeline"][0][
                    "evidence_ids"
                ],
                ["changes-0002"],
            )

    def sessions_status(self, run_id):
        with self.sessions() as session:
            return session.get(LlmRun, run_id).status

    async def test_no_incident_and_uncertain_complete_without_investigator(
        self,
    ) -> None:
        for probability, expected in [(0.2, "not_incident"), (0.5, "needs_review")]:

            async def classify(_summary, probability=probability):
                return JevJudgment(
                    model="fake-jev",
                    question_version=1,
                    probability=probability,
                    usage={},
                )

            outcome = await run_simulation(
                store=self.store,
                classifier=classify,
                session_scope=self.sessions,
            )
            self.assertEqual(outcome.status, "completed")
            self.assertEqual(
                outcome.stop_reason,
                "no_incident" if expected == "not_incident" else "needs_review",
            )
            self.assertTrue(
                all(case.outcome == expected for case in outcome.classifications)
            )
            self.assertEqual(outcome.investigations, [])
            self.assertEqual(self.sessions_status(outcome.run_id), "completed")

    async def test_provider_failure_fails_without_investigator(self) -> None:
        async def unavailable(_summary):
            raise TimeoutError("provider timeout")

        outcome = await run_simulation(
            store=self.store,
            classifier=unavailable,
            session_scope=self.sessions,
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.stop_reason, "classifier_unavailable")
        self.assertEqual(outcome.error_type, "TimeoutError")
        self.assertEqual(outcome.investigations, [])
        self.assertEqual(self.sessions_status(outcome.run_id), "failed")

    async def test_investigator_failure_marks_top_level_run_failed(self) -> None:
        async def broken(_messages, _info):
            raise RuntimeError("fake investigator failure")

        outcome = await run_simulation(
            store=self.store,
            classifier=self.classify_labeled,
            session_scope=self.sessions,
            investigator_model=FunctionModel(broken),
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.stop_reason, "agent_error")
        self.assertIsNone(outcome.investigations[0].report)
        self.assertEqual(self.sessions_status(outcome.run_id), "failed")

    async def test_token_limit_failure_is_explained_and_saved(self) -> None:
        async def over_budget(_messages, info):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "observations": [
                                {
                                    "statement": "Synthetic observation",
                                    "kind": "fact",
                                    "evidence_ids": ["changes-0002"],
                                }
                            ],
                            "candidate_causes": [],
                            "unknowns": [],
                            "next_checks": [],
                        },
                    )
                ],
                usage=RequestUsage(input_tokens=51_000, output_tokens=100),
            )

        outcome = await run_simulation(
            store=self.store,
            classifier=self.classify_labeled,
            session_scope=self.sessions,
            investigator_model=FunctionModel(over_budget),
        )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.stop_reason, "budget_exhausted")
        failure = next(
            step
            for step in outcome.workflow_steps
            if step.stage == "agent" and step.status == "failed"
        )
        self.assertIn("total_tokens_limit of 50000", failure.details["failure_detail"])
        self.assertEqual(failure.details["usage"]["input_tokens"], 51_000)
        with self.sessions() as session:
            saved = session.get(IncidentSimulationOutput, outcome.run_id)
            self.assertEqual(saved.response_payload["status"], "failed")
            self.assertEqual(session.get(LlmRun, outcome.run_id).status, "failed")

    async def test_report_limit_defaults_to_one_and_can_be_raised_to_two(self) -> None:
        async def positive(_summary):
            return JevJudgment(
                model="fake-jev", question_version=1, probability=0.9, usage={}
            )

        async def fake_investigation(_request, *, existing_run_id, **_kwargs):
            return InvestigationExecution(
                run_id=existing_run_id,
                status="completed",
                stop_reason="completed",
                draft=None,
                report=None,
                verification=None,
                tool_steps=[],
                surfaced_evidence_ids=[],
                logfire_trace_id=None,
                usage={},
            )

        with patch(
            "backend.incident_investigation.simulation.run_investigation",
            fake_investigation,
        ):
            default = await run_simulation(
                store=self.store, classifier=positive, session_scope=self.sessions
            )
            raised = await run_simulation(
                store=self.store,
                classifier=positive,
                session_scope=self.sessions,
                max_reports=2,
            )
        self.assertEqual(len(default.classifications), 2)
        self.assertEqual(len(default.investigations), 1)
        self.assertEqual(len(raised.investigations), 2)
        self.assertEqual(len(raised.detected_incidents), 2)
        self.assertTrue(
            any("budget reached" in step.summary for step in default.workflow_steps)
        )
        with self.sessions() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(LlmRun)), 2
            )

    async def test_investigations_are_serialized_across_requests(self) -> None:
        active = 0
        peak = 0
        waiting_steps = []

        async def fake_investigation(*_args, **_kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return InvestigationExecution(
                run_id=uuid.uuid4(),
                status="completed",
                stop_reason="completed",
                draft=None,
                report=None,
                verification=None,
                tool_steps=[],
                surfaced_evidence_ids=[],
                logfire_trace_id=None,
                usage={},
            )

        with patch(
            "backend.incident_investigation.service._run_investigation",
            fake_investigation,
        ):
            await asyncio.gather(
                gated_investigation(None),
                gated_investigation(None, on_step=waiting_steps.append),
            )
        self.assertEqual(peak, 1)
        self.assertEqual(
            waiting_steps[0].summary,
            "Investigator queued; one report is already running",
        )

    async def test_invalid_report_limit_is_rejected(self) -> None:
        for max_reports in (0, 4):
            with self.assertRaisesRegex(ValueError, "max_reports"):
                await run_simulation(max_reports=max_reports)
        for replay_delay_ms in (-1, 51):
            with self.assertRaisesRegex(ValueError, "replay_delay_ms"):
                await run_simulation(replay_delay_ms=replay_delay_ms)

    async def test_paced_replay_pauses_after_each_log(self) -> None:
        async def negative(_summary):
            return JevJudgment(
                model="fake-jev", question_version=1, probability=0.2, usage={}
            )

        with patch(
            "backend.incident_investigation.simulation.asyncio.sleep",
            new_callable=AsyncMock,
        ) as pause:
            outcome = await run_simulation(
                store=self.store,
                classifier=negative,
                session_scope=self.sessions,
                replay_delay_ms=25,
            )
        self.assertEqual(outcome.stop_reason, "no_incident")
        self.assertEqual(pause.await_count, 448)
        self.assertTrue(all(call.args == (0.025,) for call in pause.await_args_list))

    async def test_snapshot_excludes_future_change_and_unfinished_spans(self) -> None:
        cutoff = datetime(2026, 4, 14, 14, 19, 18, tzinfo=timezone.utc)
        snapshot = self.store.snapshot(cutoff)
        self.assertTrue(all(log.observed_at <= cutoff for log in snapshot.logs))
        self.assertTrue(all(point.observed_at <= cutoff for point in snapshot.metrics))
        self.assertTrue(all(span.ended_at <= cutoff for span in snapshot.spans))
        self.assertEqual(
            [change.evidence_id for change in snapshot.changes],
            ["changes-0001", "changes-0002"],
        )
        with self.assertRaisesRegex(ValueError, "unknown alert"):
            snapshot.scope_for_alert("alert-0001", cutoff, cutoff)

    async def test_stream_api_exposes_ordered_detection_and_report(self) -> None:
        async def fake_simulate(*, run_id, on_step, max_reports, replay_delay_ms):
            return await run_simulation(
                run_id=run_id,
                store=self.store,
                classifier=self.classify_labeled,
                session_scope=self.sessions,
                investigator_model=FunctionModel(self.investigator),
                on_step=on_step,
                max_reports=max_reports,
                replay_delay_ms=replay_delay_ms,
            )

        requested_run_id = uuid.uuid4()
        with patch("backend.incident_investigation.api.run_simulation", fake_simulate):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/agent/incident_investigation/simulate/stream",
                    json={"run_id": str(requested_run_id)},
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
        self.assertEqual(result["run_id"], str(requested_run_id))
        self.assertEqual(events[0][1]["details"]["run_id"], str(requested_run_id))
        self.assertEqual(result["status"], "completed")
        self.assertIsNotNone(result["investigations"][0]["report"])
        self.assertEqual(
            [data for kind, data in events if kind == "step"], result["workflow_steps"]
        )
        self.assertEqual(
            len(
                [step for step in result["workflow_steps"] if step["stage"] == "replay"]
            ),
            448,
        )
        self.assertEqual(
            len(
                [
                    step
                    for step in result["workflow_steps"]
                    if step["stage"] == "classifier" and step["status"] == "completed"
                ]
            ),
            2,
        )

    async def test_final_response_api_reports_nonincident_without_agent(self) -> None:
        async def negative(_summary):
            return JevJudgment(
                model="fake-jev", question_version=1, probability=0.2, usage={}
            )

        async def fake_simulate(*, run_id, max_reports, replay_delay_ms):
            return await run_simulation(
                run_id=run_id,
                store=self.store,
                classifier=negative,
                session_scope=self.sessions,
                max_reports=max_reports,
                replay_delay_ms=replay_delay_ms,
            )

        with patch("backend.incident_investigation.api.run_simulation", fake_simulate):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                response = await client.post("/agent/incident_investigation/simulate")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["stop_reason"], "no_incident")
        self.assertEqual(payload["investigations"], [])
        self.assertEqual(
            [item["outcome"] for item in payload["classifications"]],
            ["not_incident", "not_incident"],
        )

    async def test_saved_simulation_can_be_listed_and_reloaded(self) -> None:
        outcome = await run_simulation(
            store=self.store,
            classifier=self.classify_labeled,
            session_scope=self.sessions,
            investigator_model=FunctionModel(self.investigator),
        )
        with patch(
            "backend.incident_investigation.api.db_utils.get_session", self.sessions
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                listing = await client.get("/agent/incident_investigation/simulations")
                detail = await client.get(
                    f"/agent/incident_investigation/simulations/{outcome.run_id}"
                )
                missing = await client.get(
                    f"/agent/incident_investigation/simulations/{uuid.uuid4()}"
                )

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["run_id"], str(outcome.run_id))
        self.assertEqual(listing.json()[0]["report_count"], 1)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            detail.json()["workflow_steps"],
            [step.model_dump(mode="json") for step in outcome.workflow_steps],
        )
        self.assertEqual(
            detail.json()["investigations"][0]["report"]["timeline"][0]["evidence_ids"],
            ["changes-0002"],
        )
        self.assertEqual(missing.status_code, 404)

    async def test_history_route_explains_missing_migration(self) -> None:
        missing_engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @contextmanager
        def missing_sessions():
            with Session(missing_engine) as session:
                yield session

        try:
            with patch(
                "backend.incident_investigation.api.db_utils.get_session",
                missing_sessions,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://testserver"
                ) as client:
                    response = await client.get(
                        "/agent/incident_investigation/simulations"
                    )
            self.assertEqual(response.status_code, 503)
            self.assertIn("migration 005", response.json()["detail"])
        finally:
            missing_engine.dispose()

    async def test_api_validates_report_limit(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/agent/incident_investigation/simulate", json={"max_reports": 4}
            )
        self.assertEqual(response.status_code, 422)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/agent/incident_investigation/simulate",
                json={"replay_delay_ms": 51},
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
