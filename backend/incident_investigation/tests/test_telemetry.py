import unittest
from datetime import datetime, timedelta, timezone

from backend.incident_investigation.telemetry import TelemetryStore


def at(minute: int) -> datetime:
    return datetime(2026, 4, 14, 14, tzinfo=timezone.utc) + timedelta(minutes=minute)


class TelemetryStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TelemetryStore()
        cls.scope = cls.store.scope_for_alert("alert-0001", at(0), at(59))

    def test_fixture_has_multi_service_cross_source_evidence(self) -> None:
        self.assertEqual(len(self.store.manifest.services), 6)
        self.assertGreaterEqual(len(self.store.logs), 350)
        self.assertGreaterEqual(len(self.store.metrics), 1000)
        self.assertGreaterEqual(len(self.store.spans), 150)
        self.assertEqual(len(self.store.changes), 3)
        ids = [
            record.evidence_id
            for record in [*self.store.logs, *self.store.metrics, *self.store.spans, *self.store.changes]
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(record.locator.endswith(record.evidence_id) for record in self.store.logs))

    def test_incident_signals_are_retrievable_without_declaring_causation(self) -> None:
        payments_wait = self.store.get_metric_series(
            self.scope, "payments", "db_connection_wait_ms", at(10), at(45)
        ).records
        checkout_errors = self.store.get_metric_series(
            self.scope, "checkout", "error_rate", at(10), at(45)
        ).records
        inventory_errors = self.store.get_metric_series(
            self.scope, "inventory", "error_rate", at(10), at(45)
        ).records
        self.assertLess(payments_wait[0].value, 20)
        self.assertGreater(max(point.value for point in payments_wait), 2000)
        self.assertGreater(max(point.value for point in checkout_errors), 0.10)
        self.assertLess(max(point.value for point in inventory_errors), 0.01)

        storefront_changes = self.store.list_changes(self.scope, "storefront", at(0), at(45)).records
        payments_changes = self.store.list_changes(self.scope, "payments", at(0), at(45)).records
        self.assertEqual(storefront_changes[0].observed_at, at(11))
        self.assertEqual(payments_changes[0].details["db_pool_max_after"], "4")
        self.assertEqual(payments_changes[1].details["db_pool_max_after"], "40")

    def test_trace_links_services_and_discloses_missing_payments_spans(self) -> None:
        complete = self.store.inspect_trace(self.scope, "trace-0024")
        self.assertEqual({span.service for span in complete.records}, {
            "gateway", "storefront", "checkout", "payments", "inventory"
        })
        self.assertEqual(complete.coverage_gaps, [])

        sampled = self.store.inspect_trace(self.scope, "trace-0028")
        self.assertNotIn("payments", {span.service for span in sampled.records})
        self.assertEqual(len(sampled.coverage_gaps), 1)
        self.assertEqual(sampled.coverage_gaps[0].service, "payments")

    def test_logs_are_bounded_filterable_and_carry_locators(self) -> None:
        result = self.store.search_logs(self.scope, "checkout", at(17), at(25), level="ERROR", limit=3)
        self.assertEqual(len(result.records), 3)
        self.assertTrue(result.truncated)
        self.assertTrue(all(record.level == "ERROR" for record in result.records))
        traced = self.store.search_logs(self.scope, "checkout", at(19), at(20), trace_id="trace-0019")
        self.assertTrue(traced.records)
        self.assertTrue(all(record.trace_id == "trace-0019" for record in traced.records))

    def test_scope_rejects_unrelated_services_and_invalid_windows(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside investigation scope"):
            self.store.search_logs(self.scope, "email-worker", at(10), at(20))
        with self.assertRaisesRegex(ValueError, "outside investigation scope"):
            self.store.get_metric_series(self.scope, "payments", "error_rate", at(0), at(60))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.store.scope_for_alert("alert-0001", datetime(2026, 4, 14, 14), at(20))
        with self.assertRaisesRegex(ValueError, "unknown alert"):
            self.store.scope_for_alert("unknown", at(0), at(20))

    def test_query_validation_rejects_unbounded_or_unknown_requests(self) -> None:
        with self.assertRaisesRegex(ValueError, "log limit"):
            self.store.search_logs(self.scope, "checkout", at(10), at(20), limit=1000)
        with self.assertRaisesRegex(ValueError, "unknown metric"):
            self.store.get_metric_series(self.scope, "checkout", "db_pool_max", at(10), at(20))
        with self.assertRaisesRegex(ValueError, "unknown or outside"):
            self.store.inspect_trace(self.scope, "trace-nonexistent")


if __name__ == "__main__":
    unittest.main()
