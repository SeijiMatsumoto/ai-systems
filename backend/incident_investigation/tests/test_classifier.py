import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"

from backend.incident_investigation.classifier import (
    CandidateSummary,
    JevJudgment,
    classify_candidate,
    decide,
)


class FakeSpan:
    def __init__(self):
        self.attributes = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def set_attribute(self, key, value):
        self.attributes[key] = value


class FakeClient:
    def __init__(self, **_kwargs):
        self.call = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def system_one(self, **kwargs):
        self.call = kwargs
        return SimpleNamespace(
            model="jev-1.13.0",
            nouls={"active_incident": SimpleNamespace(noul=0.9)},
            usage=SimpleNamespace(
                model_dump=lambda: {"input_tokens": 500, "output_tokens": 22}
            ),
        )


class JevClassifierTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.summary = CandidateSummary(
            cluster_id="cluster-0100",
            trigger_log_id="logs-0100",
            trigger_service="checkout",
            observed_at=datetime(2026, 4, 14, 14, 19, tzinfo=timezone.utc),
            services=["checkout", "payments"],
            distinct_error_requests_last_5m=3,
            log_levels={"ERROR": 3},
            representative_messages=["Payment authorization timed out"],
            log_evidence_ids=["logs-0100"],
            latest_error_rates={"checkout": 0.143},
            metric_evidence_ids=["metrics-0010"],
        )

    async def test_live_adapter_shape_and_logfire_span(self) -> None:
        client = FakeClient()
        span = FakeSpan()
        with (
            patch(
                "backend.incident_investigation.classifier.AsyncTypeSafeClient",
                return_value=client,
            ),
            patch(
                "backend.incident_investigation.classifier.logfire.span",
                return_value=span,
            ) as span_factory,
        ):
            judgment = await classify_candidate(self.summary)

        self.assertEqual(judgment.probability, 0.9)
        self.assertEqual(client.call["model"], "jev-latest")
        self.assertEqual(client.call["state"]["cluster_id"], "cluster-0100")
        self.assertEqual(client.call["questions"]["active_incident"].type, "noul")
        self.assertEqual(span.attributes["jev.probability"], 0.9)
        self.assertEqual(span.attributes["jev.input_tokens"], 500)
        self.assertEqual(span_factory.call_args.kwargs["trigger_log_id"], "logs-0100")

    async def test_application_gate_has_review_band(self) -> None:
        for probability, expected in [
            (0.9, "incident"),
            (0.31, "not_incident"),
            (0.5, "needs_review"),
        ]:
            judgment = JevJudgment(
                model="fake", question_version=1, probability=probability, usage={}
            )
            self.assertEqual(decide(self.summary, judgment).outcome, expected)


if __name__ == "__main__":
    unittest.main()
