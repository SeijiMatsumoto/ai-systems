"""Transactional action and case workflows against an isolated database; no providers."""

import copy
import unittest
from typing import TypeVar
from unittest.mock import patch
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session

from backend.customer_support.actions import confirm
from backend.customer_support.contracts import (
    Address,
    AddressProposal,
    CancelProposal,
    CaseCategory,
    CaseRequest,
    ConfirmationRequest,
    Intent,
    ModelTurn,
)
from backend.customer_support.tests import test_workflow
from backend.customer_support.tests.test_workflow import (
    FakeJudge,
    answer,
    require_order,
    tool,
)
from backend.db.schemas import (
    Base,
    LlmRun,
    SupportCase,
    SupportConversation,
    SupportDemoSession,
    SupportOrder,
    SupportOutput,
    SupportProposal,
    SupportReceipt,
)

Row = TypeVar("Row", bound=Base)


def require_row(db: Session, model: type[Row], key: object) -> Row:
    row = db.get(model, key)
    assert row is not None
    return row


class ActionTests(test_workflow.ApiTests):
    # Reuse the isolated API setup while retaining its read-only regressions.
    def send(self, message):
        response = self.client.post(
            self.base + f"/conversations/{self.conversation}/messages",
            headers=self.headers,
            json={"message": message},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def propose(
        self, kind="cancel_order", order="order-1001", address: Address | None = None
    ):
        if kind != "cancel_order":
            assert address is not None
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)

        def proposal(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            policy = next(item for item in evidence if item["kind"] == "policy")
            order_fact = next(item for item in evidence if item["kind"] == "order")
            ids = (policy["evidence_id"], order_fact["evidence_id"])
            if kind == "cancel_order":
                op = CancelProposal(
                    kind="cancel_order", order_id=order, evidence_ids=ids
                )
            else:
                assert address is not None
                op = AddressProposal(
                    kind="change_address",
                    order_id=order,
                    address=address,
                    evidence_ids=ids,
                )
            return ModelTurn(decision="Propose checked change", proposal=op)

        self.model.script = [
            tool("policy_search", query="cancellation address change unfulfilled"),
            tool("order_detail", order_id=order),
            proposal,
        ]
        if kind == "cancel_order":
            message = f"Cancel {order}"
        else:
            assert address is not None
            message = f"Change {order} to {address.line1}, {address.city} {address.postal_code}, US"
        return self.send(message)

    def decide(self, result, decision="confirm", headers=None):
        return self.client.post(
            self.base
            + f"/conversations/{self.conversation}/proposals/{result['pending_action']['proposal_id']}/decision",
            headers=headers or self.headers,
            json={"decision": decision},
        )

    def test_cancel_requires_confirmation_and_persists(self):
        result = self.propose()
        self.assertEqual(result["disposition"], "awaiting_confirmation")
        store = self.repo.customer_store(self.store, "customer-alex")
        self.assertEqual(require_order(store, "order-1001").state, "paid")
        response = self.decide(result)
        self.assertEqual(response.status_code, 200, response.text)
        receipt = response.json()["receipt"]
        self.assertEqual(receipt["outcome"], "executed")
        self.assertFalse(receipt["refund_executed"])
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "cancelled",
        )
        # A fresh sign-in seeds only missing records, preserving mutations.
        self.repo.sign_in(self.store, "customer-alex")
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "cancelled",
        )
        repeated = self.decide(result)
        self.assertEqual(repeated.json(), response.json())
        with Session(self.engine) as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportReceipt)), 1
            )
            self.assertEqual(require_row(db, SupportOrder, "order-1001").version, 2)

    def test_address_change_and_rejection(self):
        address = Address(
            line1="200 Demo Road",
            city="Exampleville",
            postal_code="12345",
            country="US",
        )
        result = self.propose("change_address", address=address)
        self.assertEqual(result["pending_action"]["address"], address.model_dump())
        response = self.decide(result)
        self.assertEqual(response.json()["receipt"]["outcome"], "executed")
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).address,
            address,
        )
        result = self.propose()
        self.assertEqual(
            self.decide(result, "reject").json()["receipt"]["outcome"], "rejected"
        )
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "paid",
        )
        self.assertEqual(self.decide(result).status_code, 400)

    def test_stale_order_blocks_and_saves_case(self):
        result = self.propose()
        with Session(self.engine) as db:
            row = require_row(db, SupportOrder, "order-1001")
            payload = copy.deepcopy(row.payload)
            payload["fulfillment"] = "label_created"
            db.execute(
                update(SupportOrder)
                .where(SupportOrder.order_id == "order-1001")
                .values(version=2, payload=payload)
            )
            db.commit()
        response = self.decide(result)
        self.assertEqual(response.json()["receipt"]["outcome"], "blocked")
        self.assertEqual(response.json()["review_case"]["status"], "pending_review")
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "paid",
        )
        self.assertEqual(self.decide(result).json(), response.json())

    def test_stale_policy_blocks(self):
        result = self.propose()
        changed = self.store.fixture.model_copy(
            update={
                "rules": self.store.fixture.rules.model_copy(
                    update={"return_window_days": 31}
                )
            }
        )
        with patch(
            "backend.customer_support.api.MockStore.load",
            return_value=type(self.store)(changed),
        ):
            response = self.decide(result)
        self.assertEqual(response.json()["receipt"]["outcome"], "blocked")

    def test_ineligible_initial_order_creates_review_case(self):
        result = self.propose(order="order-1002")
        self.assertEqual(result["disposition"], "case_created")
        self.assertIsNone(result["pending_action"])
        self.assertIsNotNone(result["review_case"])
        self.assertEqual(result["stop_reason"], "ineligible_action_case_saved")

    def test_refund_and_outside_window_case_then_followup(self):
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)
        statement = "I want a refund for order-1005"

        def proposal(state):
            order = next(
                item
                for entry in state["observations"]
                for item in entry["results"]
                if item.get("kind") == "order"
            )
            return ModelTurn(
                decision="Request human refund review",
                proposal=CaseRequest(
                    kind="create_case",
                    category=CaseCategory.REFUND,
                    order_id="order-1005",
                    customer_statement=statement,
                    evidence_ids=(order["evidence_id"],),
                ),
            )

        self.model.script = [tool("order_detail", order_id="order-1005"), proposal]
        result = self.send(statement)
        case = result["review_case"]
        self.assertEqual(case["status"], "pending_review")
        self.assertEqual(case["category"], "refund_review")
        self.assertEqual(case["human_decision"], "not_decided")
        self.assertTrue(case["case_id"].startswith("case-"))
        self.assertIsNone(result["receipt"])
        self.runtime.judge = FakeJudge()
        self.model.script = [
            tool("case_detail", record_id=case["case_id"]),
            answer("Your case is pending review; a human has not decided it."),
        ]
        followup = self.send("What is the status of that case?")
        self.assertEqual(followup["disposition"], "answered")
        self.assertIn(case["case_id"], self.model.calls[-2]["case_ids"])

    def test_human_handoff_and_case_scope(self):
        self.runtime.judge = FakeJudge(intent=Intent.HUMAN)
        self.model.script = []
        result = self.send("I want a human")
        self.assertEqual(result["disposition"], "case_created")
        self.assertEqual(result["review_case"]["category"], "general_support")
        foreign = self.client.post(
            self.base + "/sessions", json={"customer_id": "customer-sam"}
        ).json()["token"]
        headers = {"Authorization": "Bearer " + foreign}
        url = (
            self.base
            + f"/conversations/{self.conversation}/cases/{result['review_case']['case_id']}"
        )
        self.assertEqual(self.client.get(url, headers=headers).status_code, 404)
        self.assertEqual(
            self.client.get(url, headers=self.headers).json()["status"],
            "pending_review",
        )

    def test_foreign_confirmation_and_unknown_order(self):
        result = self.propose()
        sam = self.client.post(
            self.base + "/sessions", json={"customer_id": "customer-sam"}
        ).json()["token"]
        self.assertEqual(
            self.decide(result, headers={"Authorization": "Bearer " + sam}).status_code,
            404,
        )
        result = self.propose(order="order-2001")
        self.assertEqual(result["disposition"], "handoff_needed")
        self.assertIsNone(result["review_case"])
        self.assertIsNone(result["pending_action"])

    def test_yes_does_not_execute(self):
        self.propose()
        self.model.script = []
        followup = self.send("yes")
        self.assertEqual(followup["stop_reason"], "explicit_confirmation_required")
        self.assertEqual(
            require_order(
                self.repo.customer_store(self.store, "customer-alex"), "order-1001"
            ).state,
            "paid",
        )

    def test_receipt_failure_rolls_back_order_and_proposal(self):
        result = self.propose()

        def fail(mapper, connection, target):
            raise RuntimeError("receipt persistence failed")

        event.listen(SupportReceipt, "before_insert", fail)
        try:
            with self.assertRaises(RuntimeError):
                confirm(
                    self.repo,
                    UUID(self.token),
                    UUID(self.conversation),
                    UUID(result["pending_action"]["proposal_id"]),
                    ConfirmationRequest(decision="confirm"),
                    self.store,
                )
        finally:
            event.remove(SupportReceipt, "before_insert", fail)
        with Session(self.engine) as db:
            self.assertEqual(require_row(db, SupportOrder, "order-1001").version, 1)
            self.assertEqual(
                require_row(
                    db, SupportProposal, UUID(result["pending_action"]["proposal_id"])
                ).state,
                "pending",
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportReceipt)), 0
            )
        self.assertEqual(self.decide(result).json()["receipt"]["outcome"], "executed")

    def test_case_replay_does_not_create_another_case(self):
        self.runtime.judge = FakeJudge(intent=Intent.HUMAN)
        self.model.script = []
        result = self.send("Please let me speak to a human")
        replay = self.client.post(
            self.base
            + f"/conversations/{self.conversation}/runs/{result['run_id']}/replay",
            headers=self.headers,
        )
        self.assertEqual(replay.json(), result)
        with Session(self.engine) as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportCase)), 1
            )
            case = next(iter(db.scalars(select(SupportCase))))
            self.assertFalse(case.payload["customer_statements_are_verified"])

    def test_case_output_failure_rolls_back_and_releases_reservation(self):
        self.runtime.judge = FakeJudge(intent=Intent.HUMAN)
        self.model.script = []

        def fail(mapper, connection, target):
            raise RuntimeError("output persistence failed")

        event.listen(SupportOutput, "before_insert", fail)
        try:
            with self.assertRaises(RuntimeError):
                self.send("Please let me speak to a human")
        finally:
            event.remove(SupportOutput, "before_insert", fail)
        with Session(self.engine) as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportCase)), 0
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(SupportOutput)), 0
            )
            conversation = require_row(db, SupportConversation, UUID(self.conversation))
            self.assertIsNone(conversation.active_run_id)
            self.assertEqual(next(iter(db.scalars(select(LlmRun)))).status, "failed")

    def test_proposal_grounding_and_invented_address_block(self):
        self.runtime.judge = FakeJudge(intent=Intent.ACTION, grounding=0.2)

        def rejected_proposal(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            order = next(item for item in evidence if item["kind"] == "order")
            policy = next(item for item in evidence if item["kind"] == "policy")
            return ModelTurn(
                decision="Propose",
                proposal=CancelProposal(
                    kind="cancel_order",
                    order_id="order-1001",
                    evidence_ids=(policy["evidence_id"], order["evidence_id"]),
                ),
            )

        self.model.script = [
            tool("policy_search", query="cancellation"),
            tool("order_detail", order_id="order-1001"),
            rejected_proposal,
        ]
        response = self.send("Cancel order-1001")
        self.assertEqual(response["disposition"], "clarification")
        self.assertIsNone(response["pending_action"])
        self.assertEqual(response["stop_reason"], "proposal_grounding_rejected")
        self.runtime.judge = FakeJudge(intent=Intent.ACTION)
        address = Address(
            line1="999 Invented Lane",
            city="Inventedville",
            postal_code="99999",
            country="US",
        )

        def invalid(state):
            evidence = [
                item
                for entry in state["observations"]
                for item in entry["results"]
                if "evidence_id" in item
            ]
            order = next(item for item in evidence if item["kind"] == "order")
            policy = next(item for item in evidence if item["kind"] == "policy")
            return ModelTurn(
                decision="Propose",
                proposal=AddressProposal(
                    kind="change_address",
                    order_id="order-1001",
                    address=address,
                    evidence_ids=(policy["evidence_id"], order["evidence_id"]),
                ),
            )

        self.model.script = [
            tool("policy_search", query="address change"),
            tool("order_detail", order_id="order-1001"),
            invalid,
        ]
        response = self.send("Change the address for order-1001")
        self.assertEqual(response["stop_reason"], "invented_address")

    def test_concurrent_confirmations_apply_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Barrier

        from sqlalchemy import create_engine

        from backend.customer_support.repository import SupportRepository

        result = self.propose()
        models = (
            LlmRun,
            SupportDemoSession,
            SupportConversation,
            SupportOutput,
            SupportOrder,
            SupportProposal,
            SupportCase,
            SupportReceipt,
        )
        with TemporaryDirectory() as directory:
            engine = create_engine(
                "sqlite+pysqlite:///" + str(Path(directory) / "race.sqlite"),
                connect_args={"check_same_thread": False, "timeout": 5},
            )
            Base.metadata.create_all(
                engine,
                tables=[Base.metadata.tables[model.__tablename__] for model in models],
            )
            with Session(self.engine) as source, Session(engine) as target:
                for model in models:
                    for row in source.scalars(select(model)):
                        target.add(
                            model(
                                **{
                                    column.name: getattr(row, column.name)
                                    for column in Base.metadata.tables[
                                        model.__tablename__
                                    ].columns
                                }
                            )
                        )
                    target.flush()
                target.commit()

            @contextmanager
            def sessions():
                with Session(engine) as db:
                    try:
                        yield db
                        db.commit()
                    except BaseException:
                        db.rollback()
                        raise

            repo = SupportRepository(sessions)
            barrier = Barrier(2)

            def attempt():
                barrier.wait(timeout=3)
                try:
                    return confirm(
                        repo,
                        UUID(self.token),
                        UUID(self.conversation),
                        UUID(result["pending_action"]["proposal_id"]),
                        ConfirmationRequest(decision="confirm"),
                        self.store,
                    ).receipt
                except ValueError:
                    return None  # The losing transaction may require replay after the winner commits.

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(attempt)
                    second = pool.submit(attempt)
                    self.assertTrue(
                        any(
                            receipt is not None
                            for receipt in (first.result(), second.result())
                        )
                    )
                with Session(engine) as db:
                    self.assertEqual(
                        db.scalar(select(func.count()).select_from(SupportReceipt)), 1
                    )
                    self.assertEqual(
                        require_row(db, SupportOrder, "order-1001").version, 2
                    )
            finally:
                engine.dispose()

    def test_no_refund_executor_schema(self):
        from pydantic import TypeAdapter

        from backend.customer_support.contracts import OperationProposal

        with self.assertRaises(ValidationError):
            TypeAdapter(OperationProposal).validate_python(
                {"kind": "execute_refund", "order_id": "order-1001"}
            )


if __name__ == "__main__":
    unittest.main()
