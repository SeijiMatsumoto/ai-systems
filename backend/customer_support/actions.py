"""Customer-bound persistent state and transactional mock actions; no external writes."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.db.llm_runs import complete_run, create_run, start_run
from backend.db.schemas import (
    SupportCase,
    SupportOrder,
    SupportOutput,
    SupportProposal,
    SupportReceipt,
)

from .contracts import (
    ActionKind,
    ActionReceipt,
    AddressProposal,
    CancelProposal,
    CaseCategory,
    CaseRequest,
    ConfirmationRequest,
    OperationProposal,
    Order,
    OrderLookup,
    OrderState,
    PendingAction,
    Principal,
    ReviewCase,
    SupportResponse,
    SupportStep,
)
from .retrieval import fingerprint
from .store import CustomerStore, MockStore, review_order

PROPOSAL_ADAPTER = TypeAdapter(OperationProposal)


def seed_orders(db, store: MockStore):
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    for order in store.fixture.orders:
        db.execute(
            insert(SupportOrder)
            .values(
                order_id=order.order_id,
                customer_id=order.customer_id,
                version=1,
                fixture_version=store.fixture.version,
                payload=order.model_dump(mode="json"),
            )
            .on_conflict_do_nothing(index_elements=["order_id"])
        )


class PersistentCustomerStore(CustomerStore):
    def __init__(self, store: MockStore, customer_id: str, sessions):
        super().__init__(store, Principal(customer_id=customer_id))
        self.sessions = sessions

    def orders(self) -> tuple[Order, ...]:
        with self.sessions() as db:
            return tuple(
                Order.model_validate(row.payload)
                for row in db.scalars(
                    select(SupportOrder)
                    .where(SupportOrder.customer_id == self._principal.customer_id)
                    .order_by(SupportOrder.order_id)
                )
            )

    def order(self, order_id: str) -> OrderLookup:
        # Preserve identifier validation and identical missing/foreign responses.
        from .contracts import RecordLookupRequest

        key = RecordLookupRequest(record_id=order_id).record_id
        with self.sessions() as db:
            row = db.get(SupportOrder, key)
            order = (
                Order.model_validate(row.payload)
                if row and row.customer_id == self._principal.customer_id
                else None
            )
            return OrderLookup(status="found" if order else "not_found", order=order)


def owned_order(db, customer_id, order_id):
    row = db.get(SupportOrder, order_id)
    if row is None or row.customer_id != customer_id:
        raise LookupError("Order not found")
    return row


def case_view(row: SupportCase) -> ReviewCase:
    return ReviewCase.model_validate(row.payload["case"])


def save_case(
    db,
    customer_id,
    conversation_id,
    run_id,
    operation: CaseRequest,
    key,
    evidence=(),
    context=(),
):
    existing = db.scalar(select(SupportCase).where(SupportCase.idempotency_key == key))
    if existing:
        if (
            existing.customer_id != customer_id
            or existing.conversation_id != conversation_id
        ):
            raise ValueError("Case operation scope conflict")
        return case_view(existing)
    if operation.order_id:
        owned_order(db, customer_id, operation.order_id)
    if not context:
        rows = list(
            db.scalars(
                select(SupportOutput)
                .where(SupportOutput.conversation_id == conversation_id)
                .order_by(SupportOutput.created_at.desc())
                .limit(4)
            )
        )
        context = [
            {
                "question": row.question[:500],
                "answer": SupportResponse.model_validate(row.response_payload).answer[
                    :1500
                ],
                "prior_answer_is_evidence": False,
            }
            for row in reversed(rows)
        ]
    key_id = uuid4()
    from sqlalchemy import func

    ticket_number = (
        db.scalar(
            select(func.count())
            .select_from(SupportCase)
            .where(SupportCase.conversation_id == conversation_id)
        )
        or 0
    ) + 1
    case = ReviewCase(
        ticket_number=ticket_number,
        case_id="case-" + key_id.hex,
        category=operation.category,
        order_id=operation.order_id,
        customer_statement=operation.customer_statement,
    )
    db.add(
        SupportCase(
            id=key_id,
            run_id=run_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            idempotency_key=key,
            payload={
                "case": case.model_dump(mode="json"),
                "verified_evidence": [e.model_dump(mode="json") for e in evidence],
                "customer_context": list(context)[-4:],
                "customer_statements_are_verified": False,
            },
        )
    )
    db.flush()
    return case


def save_operation(
    db, identity, conversation, response: SupportResponse, store: MockStore
):
    operation = response.approved_operation
    if operation is None:
        return response
    run_id = UUID(response.run_id)
    key = "support-operation:" + response.run_id
    if isinstance(operation, CaseRequest):
        case = save_case(
            db,
            identity.customer_id,
            conversation.id,
            run_id,
            operation,
            key,
            response.evidence,
        )
        return response.model_copy(
            update={
                "approved_operation": None,
                "review_case": case,
                "disposition": "case_created",
                "answer": (
                    "I couldn’t complete the lookup because a technical check failed. "
                    "A support case has been saved for human follow-up; this is not an answer to your question."
                    if response.stop_reason == "provider_or_validation_failure"
                    else f"Ticket #{case.ticket_number} has been sent to our support team. We’ll review your request and follow up."
                ),
                "stop_reason": response.stop_reason
                if response.stop_reason == "provider_or_validation_failure"
                else "case_saved",
            }
        )
    row = owned_order(db, identity.customer_id, operation.order_id)
    order = Order.model_validate(row.payload)
    review = review_order(order, store)
    eligible = (
        review.cancellation_state_eligible
        if isinstance(operation, CancelProposal)
        else review.address_change_state_eligible
    )
    if not eligible:
        case = save_case(
            db,
            identity.customer_id,
            conversation.id,
            run_id,
            CaseRequest(
                kind="create_case",
                category=CaseCategory.GENERAL,
                order_id=order.order_id,
                customer_statement="Requested "
                + operation.kind
                + "; order state requires human review.",
            ),
            key,
            response.evidence,
        )
        return response.model_copy(
            update={
                "approved_operation": None,
                "review_case": case,
                "disposition": "case_created",
                "answer": f"This order cannot be changed automatically in its current state. Ticket #{case.ticket_number} is saved for human review. No order change or refund was performed.",
                "stop_reason": "ineligible_action_case_saved",
            }
        )
    existing = db.scalar(
        select(SupportProposal).where(SupportProposal.idempotency_key == key)
    )
    if existing is None:
        existing = SupportProposal(
            id=uuid4(),
            run_id=run_id,
            conversation_id=conversation.id,
            customer_id=identity.customer_id,
            idempotency_key=key,
            state="pending",
            order_version=row.version,
            policy_fingerprint=fingerprint(store),
            payload={
                "operation": operation.model_dump(mode="json"),
                "evidence": [e.model_dump(mode="json") for e in response.evidence],
            },
        )
        db.add(existing)
        db.flush()
    action = PendingAction(
        proposal_id=str(existing.id),
        kind=ActionKind(operation.kind),
        order_id=operation.order_id,
        address=operation.address if isinstance(operation, AddressProposal) else None,
        state="pending",
        expected_order_version=row.version,
    )
    description = (
        "Cancel order"
        if isinstance(operation, CancelProposal)
        else "Change the shipping address for order"
    )
    address_text = (
        "\n\nReplacement address: " + operation.address.model_dump_json()
        if isinstance(operation, AddressProposal)
        else ""
    )
    return response.model_copy(
        update={
            "approved_operation": None,
            "pending_action": action,
            "disposition": "awaiting_confirmation",
            "answer": f"{description} **{operation.order_id}**? Explicit confirmation is required. No change or refund has been performed.{address_text}",
            "stop_reason": "confirmation_required",
        }
    )


def confirm(
    repo,
    token: UUID,
    conversation_id: UUID,
    proposal_id: UUID,
    decision: ConfirmationRequest,
    store: MockStore,
) -> SupportResponse:
    with repo.session_factory() as db:
        identity, conversation = repo._owned(db, token, conversation_id)
        proposal = db.get(SupportProposal, proposal_id)
        if (
            proposal is None
            or proposal.customer_id != identity.customer_id
            or proposal.conversation_id != conversation_id
        ):
            raise LookupError("Proposal not found")
        previous = db.scalar(
            select(SupportReceipt).where(SupportReceipt.proposal_id == proposal_id)
        )
        if previous:
            if previous.decision != decision.decision:
                raise ValueError("Proposal already has a different terminal decision")
            output = db.get(SupportOutput, previous.decision_run_id)
            if output is None:
                raise ValueError("Receipt output is missing")
            return SupportResponse.model_validate(output.response_payload)
        operation = PROPOSAL_ADAPTER.validate_python(proposal.payload["operation"])
        if isinstance(operation, CaseRequest):
            raise TypeError("Cases do not have an action decision state")
        run = create_run(db, "customer_support")
        reserved = db.execute(
            update(type(conversation))
            .where(
                type(conversation).id == conversation_id,
                type(conversation).active_run_id.is_(None),
            )
            .values(active_run_id=run.id)
        )
        if reserved.rowcount != 1:
            from .repository import ConversationBusy

            raise ConversationBusy("Conversation already has an active run")
        start_run(db, run.id)
        claimed = db.execute(
            update(SupportProposal)
            .where(
                SupportProposal.id == proposal_id, SupportProposal.state == "pending"
            )
            .values(state="confirmed" if decision.decision == "confirm" else "rejected")
        )
        if claimed.rowcount != 1:
            raise ValueError("Proposal already decided; retry the saved decision")
        row = owned_order(db, identity.customer_id, operation.order_id)
        order = Order.model_validate(row.payload)
        review = review_order(order, store)
        eligible = (
            review.cancellation_state_eligible
            if isinstance(operation, CancelProposal)
            else review.address_change_state_eligible
        )
        checked_version = row.version
        policy_match = fingerprint(store) == proposal.policy_fingerprint
        stale = (
            row.version != proposal.order_version
            or fingerprint(store) != proposal.policy_fingerprint
        )
        outcome, reason = "rejected", "customer_rejected"
        case = None
        if decision.decision == "confirm":
            if not eligible or stale:
                outcome, reason = (
                    "blocked",
                    "stale_state_or_policy" if stale else "ineligible_order",
                )
                proposal.state = "blocked"
                case = save_case(
                    db,
                    identity.customer_id,
                    conversation_id,
                    run.id,
                    CaseRequest(
                        kind="create_case",
                        category=CaseCategory.GENERAL,
                        order_id=order.order_id,
                        customer_statement="Confirmed change blocked: " + reason,
                    ),
                    "blocked-proposal:" + str(proposal_id),
                )
            else:
                replacement = (
                    order.model_copy(update={"state": OrderState.CANCELLED})
                    if isinstance(operation, CancelProposal)
                    else order.model_copy(update={"address": operation.address})
                )
                changed = db.execute(
                    update(SupportOrder)
                    .where(
                        SupportOrder.order_id == order.order_id,
                        SupportOrder.customer_id == identity.customer_id,
                        SupportOrder.version == proposal.order_version,
                    )
                    .values(
                        version=row.version + 1,
                        payload=replacement.model_dump(mode="json"),
                    )
                )
                if changed.rowcount != 1:
                    raise ValueError(
                        "Order changed concurrently; retry for a checked result"
                    )
                db.refresh(row)
                outcome, reason = "executed", "mock_change_saved"
        receipt = ActionReceipt(
            receipt_id=str(uuid4()),
            proposal_id=str(proposal_id),
            kind=ActionKind(operation.kind),
            order_id=order.order_id,
            outcome=outcome,
            reason=reason,
            order_version=row.version,
            case_id=case.case_id if case else None,
        )
        steps = tuple(
            SupportStep(sequence=i + 1, stage=stage, details=details)
            for i, (stage, details) in enumerate(
                [
                    (
                        "confirmation_check",
                        {
                            "proposal_id": str(proposal_id),
                            "decision": decision.decision,
                            "source_run_id": str(proposal.run_id),
                            "ownership": "passed",
                        },
                    ),
                    (
                        "execution_recheck",
                        {
                            "order_id": order.order_id,
                            "expected_version": proposal.order_version,
                            "current_version": checked_version,
                            "resulting_version": row.version,
                            "policy_match": policy_match,
                            "eligible": eligible,
                        },
                    ),
                    (
                        "transaction_receipt",
                        {
                            "receipt": receipt.model_dump(mode="json"),
                            "case": case.model_dump(mode="json") if case else None,
                        },
                    ),
                    ("stop", {"reason": reason, "outcome": outcome}),
                ]
            )
        )
        description = {
            "executed": "The confirmed mock order change is saved. No refund was issued.",
            "rejected": "The proposal was rejected. No order change was made.",
            "blocked": "The proposal was blocked because its state or policy changed. No order change was made.",
        }[outcome]
        if case:
            description += f" Ticket #{case.ticket_number} is pending human review."
        disposition: Literal[
            "action_completed", "action_rejected", "action_blocked"
        ] = (
            "action_completed"
            if outcome == "executed"
            else "action_rejected"
            if outcome == "rejected"
            else "action_blocked"
        )
        result = SupportResponse(
            run_id=str(run.id),
            conversation_id=str(conversation_id),
            disposition=disposition,
            answer=description,
            stop_reason=reason,
            receipt=receipt,
            review_case=case,
            steps=steps,
            fixture_version=store.fixture.version,
        )
        db.add(
            SupportReceipt(
                id=UUID(receipt.receipt_id),
                proposal_id=proposal_id,
                decision_run_id=run.id,
                decision=decision.decision,
                payload=receipt.model_dump(mode="json"),
            )
        )
        db.add(
            SupportOutput(
                run_id=run.id,
                conversation_id=conversation_id,
                question=f"{decision.decision} proposal {proposal_id}",
                response_payload=result.model_dump(mode="json"),
            )
        )
        conversation.active_run_id = None
        complete_run(db, run.id)
        db.flush()
        return result
