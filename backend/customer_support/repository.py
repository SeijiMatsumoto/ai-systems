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
)

from .contracts import ConversationTurn, SupportResponse
from .store import MockStore


class ConversationBusy(ValueError):
    pass


class SupportRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def sign_in(self, store: MockStore, customer_id: str) -> UUID:
        store.sign_in(customer_id)
        token = uuid4()
        with self.session_factory() as db:
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
            context = [
                ConversationTurn(
                    question=row.question,
                    answer=SupportResponse.model_validate(row.response_payload).answer,
                    order_ids=tuple(
                        e.source_id
                        for e in SupportResponse.model_validate(
                            row.response_payload
                        ).evidence
                        if e.kind == "order"
                    ),
                    product_ids=tuple(
                        e.source_id
                        for e in SupportResponse.model_validate(
                            row.response_payload
                        ).evidence
                        if e.kind == "catalog"
                    ),
                )
                for row in reversed(rows)
            ]
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

    def finish(
        self,
        token: UUID,
        conversation_id: UUID,
        question: str,
        response: SupportResponse,
    ):
        with self.session_factory() as db:
            _, conversation = self._owned(db, token, conversation_id)
            run_id = UUID(response.run_id)
            if conversation.active_run_id != run_id:
                raise ValueError("Run does not own the conversation reservation")
            db.add(
                SupportOutput(
                    run_id=run_id,
                    conversation_id=conversation_id,
                    question=question,
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
