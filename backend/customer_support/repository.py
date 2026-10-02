"""Owned conversation persistence and transaction-scoped shared run lifecycle."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update

from backend.db.llm_runs import complete_run, create_run, fail_run, start_run
from backend.db.schemas import (
    LlmRun,
    SupportConversation,
    SupportDemoSession,
    SupportOutput,
    SupportTask,
)

from .contracts import ConversationTurn, SupportResponse, SupportStep, TaskCheckpoint
from .store import MockStore
from .task_resources import resource_totals, saved_policies


class ConversationBusy(ValueError):
    pass


class SupportRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def routing_candidates(self, token, conversation_id):
        with self.session_factory() as db:
            self._owned(db, token, conversation_id)
            rows = db.scalars(
                select(SupportTask)
                .where(SupportTask.conversation_id == conversation_id)
                .order_by(SupportTask.created_at.desc(), SupportTask.id.desc())
                .limit(20)
            )
            return [
                TaskCheckpoint.model_validate(row.checkpoint)
                for row in rows
                if row.checkpoint.get("status") != "abandoned"
            ]

    def apply_task_route(self, token, conversation_id, run_id, message, route):
        with self.session_factory() as db:
            _, conversation = self._owned(db, token, conversation_id)
            if conversation.active_run_id != run_id:
                raise ValueError("Task routing does not own reservation")
            if route.route == "new":
                if route.task_kind is None:
                    return None, False
                checkpoint = TaskCheckpoint(
                    task_id=str(uuid4()), kind=route.task_kind, goal=message[:1000]
                )
                db.add(
                    SupportTask(
                        id=UUID(checkpoint.task_id),
                        conversation_id=conversation_id,
                        checkpoint=checkpoint.model_dump(mode="json"),
                        last_run_id=run_id,
                    )
                )
                return checkpoint, False
            if route.route == "clarify":
                return None, False
            row = db.get(SupportTask, UUID(route.task_id))
            if row is None or row.conversation_id != conversation_id:
                raise LookupError("Task not found")
            checkpoint = TaskCheckpoint.model_validate(row.checkpoint)
            if checkpoint.status == "abandoned":
                raise ValueError("Task has been abandoned")
            if route.route == "correct" and checkpoint.status != "awaiting_approval":
                checkpoint = checkpoint.model_copy(
                    update={
                        "goal": "Original request: "
                        + checkpoint.goal[:400]
                        + "\nCustomer correction: "
                        + message[:500],
                        "selected_order_ids": (),
                        "pending_question": None,
                        "evidence_ids": (),
                        "evidence_run_id": None,
                        "version": checkpoint.version + 1,
                        "last_answer": "",
                        "completed_steps": (),
                        "saved_policy": (),
                    }
                )
                row.checkpoint = checkpoint.model_dump(mode="json")
            return checkpoint, True

    @staticmethod
    def checkpoint_result(db, conversation_id, response):
        if response.task is None:
            return response
        row = db.get(SupportTask, UUID(response.task.task_id))
        if row is None or row.conversation_id != conversation_id:
            raise LookupError("Task not found")
        saved = TaskCheckpoint.model_validate(row.checkpoint)
        if saved.version != response.task.version:
            raise ValueError("Stale task checkpoint")
        status = (
            "abandoned"
            if response.stop_reason == "task_abandoned"
            else "completed"
            if response.receipt or response.review_case
            else "awaiting_approval"
            if response.pending_action
            else "awaiting_approval"
            if saved.status == "awaiting_approval"
            else "completed"
            if saved.status == "completed" and saved.case_ids
            else "failed"
            if response.stop_reason in {"interrupted", "provider_or_validation_failure"}
            else "awaiting_clarification"
            if response.disposition == "clarification"
            else "awaiting_customer_decision"
        )
        # Keep only cited targets, not every record fetched during discovery.
        targets = tuple(
            dict.fromkeys(e.source_id for e in response.evidence if e.kind == "order")
        )
        checkpoint = saved.model_copy(
            update={
                "status": status,
                "resources": resource_totals(
                    saved.resources, response.usage, response.steps
                ),
                "saved_policy": saved_policies(saved.saved_policy, response),
                "version": saved.version + 1,
                "selected_order_ids": targets or saved.selected_order_ids,
                "pending_proposal_id": response.pending_action.proposal_id
                if response.pending_action
                else saved.pending_proposal_id,
                "pending_question": response.answer
                if status in {"awaiting_clarification", "awaiting_approval"}
                else None,
                "last_answer": response.answer,
                "case_ids": (response.review_case.case_id,)
                if response.review_case
                else saved.case_ids,
                "completed_steps": tuple(
                    dict.fromkeys(
                        [
                            *saved.completed_steps,
                            *[
                                s.stage
                                for s in response.steps
                                if s.stage
                                in {
                                    "tool_result",
                                    "citation_check",
                                    "grounding_check",
                                    "proposal_check",
                                    "proposal_state_check",
                                    "proposal_grounding_check",
                                    "execution_recheck",
                                }
                            ],
                        ]
                    )
                ),
                "evidence_run_id": response.run_id
                if response.evidence
                else saved.evidence_run_id,
                "evidence_ids": tuple(e.evidence_id for e in response.evidence)
                if response.evidence
                else saved.evidence_ids,
            }
        )
        row.checkpoint = checkpoint.model_dump(mode="json")
        row.last_run_id = UUID(response.run_id)
        prior = list(response.steps[:-1])
        prior.append(
            SupportStep(
                sequence=len(prior) + 1,
                stage="task_checkpoint",
                details=checkpoint.model_dump(mode="json"),
            )
        )
        prior.append(response.steps[-1].model_copy(update={"sequence": len(prior) + 1}))
        return response.model_copy(update={"task": checkpoint, "steps": tuple(prior)})

    def sign_in(self, store: MockStore, customer_id: str) -> UUID:
        store.sign_in(customer_id)
        token = uuid4()
        with self.session_factory() as db:
            from .actions import seed_orders

            seed_orders(db, store)
            db.add(SupportDemoSession(id=token, customer_id=customer_id))
        return token

    @staticmethod
    def _identity(db, token: UUID):
        identity = db.get(SupportDemoSession, token)
        if identity is None:
            raise LookupError("Unknown demo session")
        return identity

    @classmethod
    def _owned(cls, db, token: UUID, conversation_id: UUID):
        identity = cls._identity(db, token)
        conversation = db.get(SupportConversation, conversation_id)
        if conversation is None or conversation.session_id != identity.id:
            raise LookupError("Conversation not found")
        return identity, conversation

    def create_conversation(self, token: UUID) -> UUID:
        with self.session_factory() as db:
            self._identity(db, token)
            key = uuid4()
            db.add(SupportConversation(id=key, session_id=token))
        return key

    def conversations(self, token: UUID):
        with self.session_factory() as db:
            self._identity(db, token)
            return [
                {
                    "conversation_id": str(c.id),
                    "created_at": c.created_at.isoformat(),
                    "busy": c.active_run_id is not None,
                }
                for c in db.scalars(
                    select(SupportConversation)
                    .where(SupportConversation.session_id == token)
                    .order_by(SupportConversation.created_at.desc())
                    .limit(20)
                )
            ]

    def history(self, token: UUID, conversation_id: UUID):
        with self.session_factory() as db:
            self._owned(db, token, conversation_id)
            rows = list(
                db.scalars(
                    select(SupportOutput)
                    .where(SupportOutput.conversation_id == conversation_id)
                    .order_by(
                        SupportOutput.created_at.desc(), SupportOutput.run_id.desc()
                    )
                    .limit(20)
                )
            )
            return [
                {
                    "question": row.question,
                    "response": SupportResponse.model_validate(
                        row.response_payload
                    ).model_dump(mode="json"),
                }
                for row in reversed(rows)
            ]

    def begin(self, token: UUID, conversation_id: UUID):
        with self.session_factory() as db:
            identity, _ = self._owned(db, token, conversation_id)
            rows = list(
                db.scalars(
                    select(SupportOutput)
                    .where(SupportOutput.conversation_id == conversation_id)
                    .order_by(
                        SupportOutput.created_at.desc(), SupportOutput.run_id.desc()
                    )
                    .limit(4)
                )
            )
            context = []
            for row in reversed(rows):
                saved = SupportResponse.model_validate(row.response_payload)
                context.append(
                    ConversationTurn(
                        task_id=saved.task.task_id if saved.task else None,
                        stop_reason=saved.stop_reason,
                        question=row.question,
                        answer=saved.answer,
                        case_ids=(saved.review_case.case_id,)
                        if saved.review_case
                        else (),
                        proposal_ids=(saved.pending_action.proposal_id,)
                        if saved.pending_action
                        else (),
                        order_ids=tuple(
                            e.source_id for e in saved.evidence if e.kind == "order"
                        ),
                        product_ids=tuple(
                            e.source_id for e in saved.evidence if e.kind == "catalog"
                        ),
                    )
                )
            run = create_run(db, "customer_support")
            reservation = db.execute(
                update(SupportConversation)
                .where(
                    SupportConversation.id == conversation_id,
                    SupportConversation.active_run_id.is_(None),
                )
                .values(active_run_id=run.id)
            )
            if reservation.rowcount != 1:
                raise ConversationBusy(
                    "This conversation already has a running message"
                )
            start_run(db, run.id)
            run_id, customer_id = run.id, identity.customer_id
        return run_id, customer_id, context

    def customer_store(self, store, customer_id):
        from .actions import PersistentCustomerStore

        return PersistentCustomerStore(store, customer_id, self.session_factory)

    def cases(self, token, conversation_id):
        from backend.db.schemas import SupportCase

        from .actions import case_view

        with self.session_factory() as db:
            identity, _ = self._owned(db, token, conversation_id)
            return [
                case_view(row)
                for row in db.scalars(
                    select(SupportCase).where(
                        SupportCase.customer_id == identity.customer_id,
                        SupportCase.conversation_id == conversation_id,
                    )
                )
            ]

    def case(self, token, conversation_id, case_id):
        from backend.db.schemas import SupportCase

        from .actions import case_view
        from .contracts import RecordLookupRequest

        key = RecordLookupRequest(record_id=case_id).record_id
        if not key.startswith("case-"):
            return None
        try:
            case_uuid = UUID(hex=key[5:])
        except ValueError:
            return None
        with self.session_factory() as db:
            identity, _ = self._owned(db, token, conversation_id)
            row = db.get(SupportCase, case_uuid)
            return (
                case_view(row)
                if row
                and row.customer_id == identity.customer_id
                and row.conversation_id == conversation_id
                else None
            )

    def saved_result(self, token, conversation_id, run_id):
        with self.session_factory() as db:
            self._owned(db, token, conversation_id)
            row = db.get(SupportOutput, run_id)
            if row is None or row.conversation_id != conversation_id:
                raise LookupError("Saved operation not found")
            return SupportResponse.model_validate(row.response_payload)

    def pending(self, token, conversation_id):
        from backend.db.schemas import SupportProposal

        with self.session_factory() as db:
            identity, _ = self._owned(db, token, conversation_id)
            return [
                str(row.id)
                for row in db.scalars(
                    select(SupportProposal).where(
                        SupportProposal.customer_id == identity.customer_id,
                        SupportProposal.conversation_id == conversation_id,
                        SupportProposal.state == "pending",
                    )
                )
            ]

    def finish(
        self,
        token: UUID,
        conversation_id: UUID,
        question: str,
        response: SupportResponse,
        store: MockStore | None = None,
    ):
        with self.session_factory() as db:
            identity, conversation = self._owned(db, token, conversation_id)
            run_id = UUID(response.run_id)
            if conversation.active_run_id != run_id:
                raise ValueError("Run does not own the conversation reservation")
            from .actions import save_operation

            response = (
                save_operation(db, identity, conversation, response, store)
                if store is not None
                else response
            )
            if response.approved_operation is not None:
                raise ValueError("Operation persistence requires the current store")
            if response.pending_action or response.review_case:
                prior = list(response.steps[:-1])
                prior.append(
                    SupportStep(
                        sequence=len(prior) + 1,
                        stage="operation_persistence",
                        details={
                            "proposal": response.pending_action.model_dump(mode="json")
                            if response.pending_action
                            else None,
                            "case": response.review_case.model_dump(mode="json")
                            if response.review_case
                            else None,
                        },
                    )
                )
                prior.append(
                    SupportStep(
                        sequence=len(prior) + 1,
                        stage="stop",
                        details={
                            "reason": response.stop_reason,
                            "disposition": response.disposition,
                        },
                    )
                )
                response = response.model_copy(update={"steps": tuple(prior)})
            response = self.checkpoint_result(db, conversation_id, response)
            db.add(
                SupportOutput(
                    run_id=run_id,
                    conversation_id=conversation_id,
                    question=question,
                    task_id=UUID(response.task.task_id) if response.task else None,
                    created_at=datetime.now(timezone.utc),
                    response_payload=response.model_dump(mode="json"),
                )
            )
            if response.stop_reason in {
                "provider_or_validation_failure",
                "interrupted",
            }:
                fail_run(db, run_id)
            else:
                complete_run(db, run_id)
            conversation.active_run_id = None
            db.flush()
        return response

    def attach_trace(
        self, token: UUID, conversation_id: UUID, run_id: UUID, trace_id: str | None
    ):
        if trace_id is None:
            return
        with self.session_factory() as db:
            _, conversation = self._owned(db, token, conversation_id)
            if conversation.active_run_id != run_id:
                raise ValueError("Trace does not own the reservation")
            run = db.get(LlmRun, run_id)
            if run is None:
                raise LookupError("Run not found")
            run.logfire_trace_id = trace_id

    def abort(self, token, conversation_id, run_id):
        with self.session_factory() as db:
            _, conversation = self._owned(db, token, conversation_id)
            if conversation.active_run_id == run_id:
                fail_run(db, run_id)
                conversation.active_run_id = None
