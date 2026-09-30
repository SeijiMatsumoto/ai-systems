"""Exercise each paid smoke script with fake model responses."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"

from backend.incident_investigation.classifier import JevJudgment
from backend.incident_investigation.detection import REPLAY_FIXTURE_DIR, replay_logs
from backend.incident_investigation.simulation import build_summary, detected_from
from backend.incident_investigation.smoketests import (
    smoketest_checkout_jev,
    smoketest_inventory_jev,
    smoketest_investigator_draft,
    smoketest_investigator_query,
)
from backend.incident_investigation.smoketests._common import (
    checkout_context,
    load_candidate,
)
from backend.incident_investigation.telemetry import TelemetryStore


class SingleRequestSmokeTests(unittest.IsolatedAsyncioTestCase):
    def test_pinned_candidates_match_current_fixture(self) -> None:
        store = TelemetryStore(REPLAY_FIXTURE_DIR)
        seen = []
        summaries = {}
        for step in replay_logs(store):
            seen.append(step)
            if step.decision == "candidate":
                summaries[step.log.service] = build_summary(step, seen, store)
        for service in ("checkout", "inventory"):
            self.assertEqual(
                load_candidate(f"{service}_candidate.json"), summaries[service]
            )
        _, _, snapshot = checkout_context()
        detected = detected_from(summaries["checkout"], store)
        self.assertEqual(snapshot.manifest.window_start, store.manifest.window_start)
        self.assertEqual(snapshot.logs[-1].observed_at <= detected.observed_at, True)

    async def test_each_jev_script_checks_its_own_judgment(self) -> None:
        for module, probability in (
            (smoketest_checkout_jev, 0.87),
            (smoketest_inventory_jev, 0.48),
        ):
            judgment = JevJudgment(
                model="fake", question_version=1, probability=probability, usage={}
            )
            with (
                patch.object(
                    module,
                    "classify_candidate",
                    new=AsyncMock(return_value=judgment),
                ) as classifier,
                patch.object(module, "emit"),
            ):
                await module.check()
            classifier.assert_awaited_once()

    async def test_query_script_stops_after_one_model_response(self) -> None:
        async def choose_query(messages, info):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_logs",
                        {
                            "service": "checkout",
                            "start": "2026-04-14T14:00:00Z",
                            "end": "2026-04-14T14:19:18Z",
                            "level": "ERROR",
                            "limit": 10,
                        },
                    )
                ]
            )

        with patch.object(smoketest_investigator_query, "emit") as output:
            await smoketest_investigator_query.check(FunctionModel(choose_query))
        self.assertEqual(output.call_args.args[0]["usage"]["requests"], 1)
        self.assertEqual(output.call_args.args[0]["tool_name"], "search_logs")

    async def test_draft_script_checks_citations_without_running_tools(self) -> None:
        async def write_draft(messages, info):
            self.assertEqual(len(messages), 7)
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "observations": [
                                {
                                    "statement": "Checkout requests failed.",
                                    "kind": "fact",
                                    "evidence_ids": ["logs-0115"],
                                }
                            ],
                            "candidate_causes": [],
                            "unknowns": [],
                            "next_checks": [],
                        },
                    )
                ]
            )

        with patch.object(smoketest_investigator_draft, "emit") as output:
            await smoketest_investigator_draft.check(FunctionModel(write_draft))
        self.assertEqual(output.call_args.args[0]["usage"]["requests"], 1)
        self.assertEqual(
            output.call_args.args[0]["draft"]["observations"][0]["evidence_ids"],
            ["logs-0115"],
        )
        self.assertTrue(output.call_args.args[0]["verification_passed"])

    async def test_draft_rejects_mismatched_pinned_tool_result(self) -> None:
        with (
            patch.dict(
                smoketest_investigator_draft.EVIDENCE,
                {"get_metric_series": ["metrics-0401"]},
            ),
            self.assertRaisesRegex(AssertionError, "expected checkout"),
        ):
            await smoketest_investigator_draft.check(
                FunctionModel(lambda messages, info: None)
            )


if __name__ == "__main__":
    unittest.main()
