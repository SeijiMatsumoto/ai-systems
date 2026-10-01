"""Offline component checks: no model, provider, database, or external writes."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.customer_support.contracts import (
    Compatibility,
    CompatibilityStatus,
    OrderLookup,
    StoreFixture,
    SupportRequest,
)
from backend.customer_support.store import DEFAULT_FIXTURE, FixtureError, MockStore
from backend.customer_support.tests.test_workflow import require_order


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = MockStore.load()
        self.alex = self.store.sign_in("customer-alex")
        self.payload = json.loads(DEFAULT_FIXTURE.read_text())

    def test_request_normalizes_and_rejects_identity(self):
        request = SupportRequest(
            conversation_id="chat-1", message="  Where is my order?  "
        )
        self.assertEqual(request.message, "Where is my order?")
        for message in ("   ", "x" * 2001):
            with self.assertRaises(ValidationError):
                SupportRequest(conversation_id="chat-1", message=message)
        with self.assertRaises(ValidationError):
            SupportRequest.model_validate(
                {
                    "conversation_id": "chat-1",
                    "message": "hello",
                    "customer_id": "customer-sam",
                }
            )

    def test_customer_order_isolation(self):
        self.assertEqual(len(self.alex.orders()), 5)
        self.assertTrue(
            all(o.customer_id == "customer-alex" for o in self.alex.orders())
        )
        foreign = self.alex.order("order-2001")
        self.assertEqual(foreign, self.alex.order("order-missing"))
        self.assertEqual(foreign.status, "not_found")
        self.assertIsNone(foreign.order)
        self.assertEqual(
            self.store.sign_in("customer-sam").order("order-2001").status, "found"
        )
        with self.assertRaises(TypeError):
            arguments: dict[str, Any] = {
                "order_id": "order-2001",
                "customer_id": "customer-sam",
            }
            self.alex.order(**arguments)

    def test_unknown_identity_rejected(self):
        with self.assertRaises(ValueError):
            self.store.sign_in("missing")

    def test_order_states(self):
        self.assertEqual(
            [
                require_order(self.alex, f"order-100{i}").fulfillment
                for i in range(1, 5)
            ],
            ["unfulfilled", "label_created", "shipped", "delivered"],
        )
        recent = require_order(self.alex, "order-1004").delivered_on
        assert recent is not None
        self.assertEqual((self.store.fixture.scenario_date - recent).days, 16)
        older = require_order(self.alex, "order-1005").delivered_on
        assert older is not None
        self.assertGreater((self.store.fixture.scenario_date - older).days, 30)

    def test_policy_and_account_are_distinct(self):
        self.assertEqual(self.store.policies("order-1001"), ())
        self.assertEqual(self.alex.order("returns").status, "not_found")
        self.assertEqual(len(self.store.policies("returns")), 1)
        self.assertIn("AI cannot issue refunds", self.store.policies("returns")[0].text)
        self.assertIsNone(self.store.product("missing"))

    def test_known_and_unknown_compatibility(self):
        known = self.store.compatibility("eos-r50", "rf-s18-45")
        self.assertEqual(known.status, "compatible")
        self.assertIsNotNone(known.provenance)
        for body, lens in [
            ("eos-r8", "rf-s18-45"),
            ("missing", "rf24-50"),
            ("rf24-50", "eos-r8"),
        ]:
            self.assertEqual(self.store.compatibility(body, lens).status, "unknown")

    def test_explicit_incompatible_result(self):
        self.payload["compatibility"][0]["status"] = "incompatible"
        store = MockStore(StoreFixture.model_validate(self.payload))
        self.assertEqual(
            store.compatibility("eos-r50", "rf-s18-45").status, "incompatible"
        )

    def test_compatibility_cannot_assert_without_evidence(self):
        with self.assertRaises(ValidationError):
            Compatibility(
                body_id="body",
                lens_id="lens",
                status=CompatibilityStatus.COMPATIBLE,
                explanation="guess",
            )

    def test_bounded_lookup_arguments(self):
        for lookup in [self.alex.order, self.store.product, self.store.policies]:
            for invalid in ["", "../secret", "x" * 65]:
                with self.assertRaises(ValidationError):
                    lookup(invalid)
        with self.assertRaises(ValidationError):
            self.store.compatibility("../body", "lens")

    def test_duplicate_and_broken_references(self):
        for mutate in [
            lambda x: x["orders"].append(x["orders"][0]),
            lambda x: x["products"].append(x["products"][0]),
            lambda x: x["customers"].append(x["customers"][0]),
            lambda x: x["policies"].append(x["policies"][0]),
            lambda x: x["compatibility"].append(x["compatibility"][0]),
            lambda x: x["orders"][0].update(customer_id="missing"),
            lambda x: x["orders"][0]["lines"][0].update(product_id="missing"),
            lambda x: x["compatibility"][0].update(body_id="missing"),
            lambda x: x["compatibility"][0].update(body_id="rf24-50"),
        ]:
            with self.subTest(mutate=mutate):
                payload = json.loads(DEFAULT_FIXTURE.read_text())
                mutate(payload)
                with self.assertRaises(ValidationError):
                    StoreFixture.model_validate(payload)

    def test_invalid_dates_and_shapes(self):
        for mutate in [
            lambda x: x["orders"][0].update(delivered_on="2026-09-30"),
            lambda x: x["orders"][3].update(delivered_on="2026-01-01"),
            lambda x: x["orders"][0].update(placed_on="2027-01-01"),
            lambda x: x["policies"][0].update(effective_on="2027-01-01"),
            lambda x: x["products"][0].update(mount=None),
            lambda x: x["orders"][0]["lines"][0].update(quantity=True),
        ]:
            payload = json.loads(DEFAULT_FIXTURE.read_text())
            mutate(payload)
            with self.assertRaises(ValidationError):
                StoreFixture.model_validate(payload)

    def test_malformed_or_missing_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            with self.assertRaises(FixtureError):
                MockStore.load(path)
            for content in ["not-json", "{}"]:
                path.write_text(content)
                with self.assertRaises(FixtureError):
                    MockStore.load(path)

    def test_immutable_observations(self):
        with self.assertRaises(ValidationError):
            require_order(self.alex, "order-1001").customer_id = "customer-sam"

    def test_lookup_payload_consistency(self):
        with self.assertRaises(ValidationError):
            OrderLookup(status="found")


if __name__ == "__main__":
    unittest.main()
