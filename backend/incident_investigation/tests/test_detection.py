import json
import unittest
from pathlib import Path

from backend.incident_investigation.detection import (
    REPLAY_FIXTURE_DIR,
    normalize_message,
    replay_logs,
)
from backend.incident_investigation.telemetry import TelemetryStore


class DetectionReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TelemetryStore(REPLAY_FIXTURE_DIR)
        cls.steps = list(replay_logs(cls.store))
        cls.labels = json.loads(
            (REPLAY_FIXTURE_DIR / "expected_detection.json").read_text(encoding="utf-8")
        )

    def test_fixture_replays_every_log_in_timestamp_order(self) -> None:
        self.assertIsNone(self.store.manifest.alert)
        self.assertEqual(len(self.steps), len(self.store.logs))
        self.assertEqual(len(self.steps), 448)
        self.assertEqual(
            [step.log.observed_at for step in self.steps],
            sorted(step.log.observed_at for step in self.steps),
        )
        self.assertEqual(
            {step.log.evidence_id for step in self.steps},
            {log.evidence_id for log in self.store.logs},
        )
        self.assertTrue(
            all(step.log.locator.startswith("fixtures/v2/") for step in self.steps)
        )

    def test_repeated_logs_group_and_link_correlated_services(self) -> None:
        checkout = [
            step
            for step in self.steps
            if step.log.service == "checkout" and step.log.level == "ERROR"
        ]
        self.assertEqual(len({step.group_id for step in checkout}), 1)
        self.assertEqual(checkout[2].group_count, 3)
        self.assertEqual(
            checkout[2].cluster_services, ["checkout", "gateway", "payments"]
        )
        matching_gateway = next(
            step
            for step in self.steps
            if step.log.service == "gateway"
            and step.log.level == "ERROR"
            and step.log.attributes.get("request_id")
            == checkout[2].log.attributes.get("request_id")
        )
        self.assertEqual(matching_gateway.cluster_id, checkout[2].cluster_id)
        self.assertEqual(
            normalize_message("HTTP 503 for order 123"), "http 503 for order <n>"
        )

    def test_candidates_match_labeled_cases_and_are_emitted_once(self) -> None:
        candidates = [step for step in self.steps if step.decision == "candidate"]
        self.assertEqual(len(candidates), 2)
        expected = {
            (case["service"], case["message"])
            for case in self.labels["candidate_cases"]
        }
        self.assertEqual(
            {(step.log.service, step.log.message) for step in candidates}, expected
        )
        self.assertTrue(all(step.distinct_error_requests == 3 for step in candidates))
        self.assertEqual(len({step.cluster_id for step in candidates}), 2)
        self.assertTrue(
            any(
                step.decision == "duplicate_candidate"
                for step in self.steps
                if step.cluster_id == candidates[0].cluster_id
            )
        )
        self.assertEqual(
            [
                step
                for step in self.steps
                if step.log.service == "email-worker" and step.decision == "candidate"
            ],
            [],
        )

    def test_generator_is_stable(self) -> None:
        import subprocess
        import sys

        paths = sorted(Path(REPLAY_FIXTURE_DIR).iterdir())
        before = {path.name: path.read_bytes() for path in paths}
        subprocess.run(
            [sys.executable, str(REPLAY_FIXTURE_DIR.parent / "generate_v2.py")],
            check=True,
        )
        self.assertEqual(before, {path.name: path.read_bytes() for path in paths})


if __name__ == "__main__":
    unittest.main()
