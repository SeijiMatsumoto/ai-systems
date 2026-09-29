import os
import unittest
import uuid
from unittest.mock import patch

os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"

from fastapi.testclient import TestClient

from backend.incident_investigation.agent import DraftClaim, InvestigationDraft
from backend.incident_investigation.contracts import (
    InvestigationRequest,
    VerificationResult,
)
from backend.incident_investigation.service import InvestigationExecution
from backend.incident_investigation.telemetry import TelemetryStore
from backend.incident_investigation.verification import verify_report
from backend.main import app


def draft(*, observations, causes=None, unknowns=None) -> InvestigationDraft:
    return InvestigationDraft(
        observations=observations,
        candidate_causes=causes or [],
        unknowns=unknowns or [],
        next_checks=["Ask the payments owner to confirm the pool setting."],
    )


class ReportVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TelemetryStore()
        cls.scope = cls.store.scope_for_alert(
            "alert-0001",
            cls.store.manifest.window_start,
            cls.store.manifest.window_end,
        )

    def verify(self, report_draft, ids):
        return verify_report(
            report_draft,
            store=self.store,
            scope=self.scope,
            surfaced_evidence_ids=set(ids),
        )

    def test_valid_report_sorts_timeline_and_discloses_trace_gap(self) -> None:
        report, result = self.verify(
            draft(
                observations=[
                    DraftClaim(
                        statement="Payments pool configuration changed.",
                        kind="fact",
                        evidence_ids=["changes-0002"],
                    ),
                    DraftClaim(
                        statement="A storefront release occurred nearby.",
                        kind="correlation",
                        evidence_ids=["changes-0001"],
                    ),
                ],
                causes=[
                    DraftClaim(
                        statement="The smaller payments pool may have contributed to errors.",
                        kind="hypothesis",
                        evidence_ids=["changes-0002"],
                    )
                ],
            ),
            {"changes-0001", "changes-0002"},
        )
        self.assertTrue(result.passed)
        self.assertEqual(
            [claim.evidence_ids[0] for claim in report.timeline],
            [
                "changes-0001",
                "changes-0002",
            ],
        )
        self.assertEqual(report.likely_causes[0].kind, "hypothesis")
        self.assertEqual(report.evidence[0].source, "change")
        self.assertEqual(
            report.evidence[0].locator,
            "fixtures/v1/changes.jsonl#changes-0001",
        )
        self.assertIn('"db_pool_max_after": "4"', report.evidence[1].excerpt)
        self.assertEqual(len(report.coverage_gaps), 1)
        self.assertIn("trace coverage gap for payments", report.unknowns[0])
        self.assertTrue(report.review_required)

    def test_unknown_and_unsurfaced_citations_fail(self) -> None:
        report, result = self.verify(
            draft(
                observations=[
                    DraftClaim(
                        statement="Unsupported observation",
                        kind="fact",
                        evidence_ids=["changes-0002", "invented-0001"],
                    )
                ]
            ),
            set(),
        )
        self.assertIsNone(report)
        self.assertEqual(
            {issue.code for issue in result.issues},
            {"not_surfaced", "unknown_evidence"},
        )

    def test_out_of_scope_and_wrong_claim_kind_fail(self) -> None:
        unrelated = next(
            log for log in self.store.logs if log.service == "email-worker"
        )
        report, result = self.verify(
            draft(
                observations=[
                    DraftClaim(
                        statement="The storefront release caused the incident.",
                        kind="hypothesis",
                        evidence_ids=["changes-0001"],
                    )
                ],
                causes=[
                    DraftClaim(
                        statement="Email worker caused checkout errors.",
                        kind="fact",
                        evidence_ids=[unrelated.evidence_id],
                    )
                ],
            ),
            {"changes-0001", unrelated.evidence_id},
        )
        self.assertIsNone(report)
        self.assertEqual(
            {issue.code for issue in result.issues},
            {"invalid_kind", "outside_scope"},
        )

    def test_empty_report_fails(self) -> None:
        report, result = self.verify(draft(observations=[]), set())
        self.assertIsNone(report)
        self.assertEqual(result.issues[0].code, "empty_report")


class IncidentApiTests(unittest.TestCase):
    def test_route_serializes_cited_report(self) -> None:
        store = TelemetryStore()
        scope = store.scope_for_alert(
            "alert-0001",
            store.manifest.window_start,
            store.manifest.window_end,
        )
        report, verification = verify_report(
            draft(
                observations=[
                    DraftClaim(
                        statement="Payments pool configuration changed.",
                        kind="fact",
                        evidence_ids=["changes-0002"],
                    )
                ]
            ),
            store=store,
            scope=scope,
            surfaced_evidence_ids={"changes-0002"},
        )
        outcome = InvestigationExecution(
            run_id=uuid.uuid4(),
            status="completed",
            stop_reason="completed",
            draft=None,
            report=report,
            verification=verification,
            tool_steps=[],
            surfaced_evidence_ids=["changes-0002"],
            logfire_trace_id=None,
            usage={},
        )

        async def fake_run(request: InvestigationRequest):
            return outcome

        with patch("backend.incident_investigation.api.run_investigation", fake_run):
            response = TestClient(app).post(
                "/agent/incident_investigation",
                json={
                    "service": "checkout",
                    "alert_id": "alert-0001",
                    "window_start": "2026-04-14T14:00:00Z",
                    "window_end": "2026-04-14T14:59:00Z",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["report"]["evidence"][0]["evidence_id"], "changes-0002"
        )
        self.assertTrue(payload["report"]["review_required"])
        self.assertTrue(payload["verification"]["passed"])

    def test_route_exposes_review_state_and_verification_failure(self) -> None:
        outcome = InvestigationExecution(
            run_id=uuid.uuid4(),
            status="failed",
            stop_reason="verification_failed",
            draft=None,
            report=None,
            verification=VerificationResult(
                passed=False,
                issues=[
                    {
                        "code": "empty_report",
                        "path": "observations",
                    }
                ],
            ),
            tool_steps=[],
            surfaced_evidence_ids=[],
            logfire_trace_id=None,
            usage={},
        )

        async def fake_run(request: InvestigationRequest):
            return outcome

        with patch("backend.incident_investigation.api.run_investigation", fake_run):
            response = TestClient(app).post(
                "/agent/incident_investigation",
                json={
                    "service": "checkout",
                    "alert_id": "alert-0001",
                    "window_start": "2026-04-14T14:00:00Z",
                    "window_end": "2026-04-14T14:59:00Z",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["run_id"], str(outcome.run_id))
        self.assertEqual(payload["stop_reason"], "verification_failed")
        self.assertIsNone(payload["report"])
        self.assertEqual(payload["verification"]["issues"][0]["code"], "empty_report")
        self.assertNotIn("draft", payload)

    def test_route_rejects_invalid_scope(self) -> None:
        async def fake_run(request: InvestigationRequest):
            raise ValueError("unknown alert ID")

        with patch("backend.incident_investigation.api.run_investigation", fake_run):
            response = TestClient(app).post(
                "/agent/incident_investigation",
                json={
                    "service": "checkout",
                    "alert_id": "unknown",
                    "window_start": "2026-04-14T14:00:00Z",
                    "window_end": "2026-04-14T14:59:00Z",
                },
            )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
