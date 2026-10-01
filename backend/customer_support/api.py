"""Owned support conversations and ordered progress events; no action endpoints."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Annotated, Never
from uuid import UUID

import logfire
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.db import db_utils
from backend.internal_knowledge_action.embedding import (
    EmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from backend.observability import EXPORT_ENABLED

from .contracts import (
    ConfirmationRequest,
    ConversationTurn,
    DemoSignIn,
    MessageRequest,
    PolicyIndex,
    SupportRequest,
    SupportResponse,
    SupportStep,
)
from .providers import Judge, LiveJevJudge, LiveSupportModel, SupportModel
from .repository import ConversationBusy, SupportRepository
from .retrieval import IndexUnavailable, load_index
from .service import run_support
from .store import MockStore

router = APIRouter(prefix="/agent/customer_support", tags=["customer_support"])


def repository():
    return SupportRepository(db_utils.get_session)


def session_token(authorization: Annotated[str, Header()]):
    try:
        scheme, value = authorization.split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError()
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(401, "Use a valid demo session token") from exc


@dataclass
class Runtime:
    store: MockStore
    model: SupportModel
    judge: Judge
    index: PolicyIndex | None
    embedder: EmbeddingProvider


def runtime():
    store = MockStore.load()
    try:
        index = load_index()
    except IndexUnavailable:
        index = None
    # Only explicitly ingested mock indexes select fake query vectors.
    embedder: EmbeddingProvider = (
        MockEmbeddingProvider()
        if index and index.embedding_model == "mock-embedding-v1"
        else OpenAIEmbeddingProvider()
    )
    return Runtime(store, LiveSupportModel(), LiveJevJudge(), index, embedder)


def error(exc) -> Never:
    if isinstance(exc, LookupError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ConversationBusy):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, SQLAlchemyError):
        original = getattr(exc, "orig", None)
        code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
        logging.getLogger(__name__).warning(
            "Support persistence failure: %s; SQLSTATE=%s", type(exc).__name__, code
        )
        raise HTTPException(
            503,
            "Support setup is incomplete. Please contact the demo administrator."
            if code == "42P01"
            else "Support is temporarily unavailable. Please retry.",
        ) from exc
    raise HTTPException(400, str(exc)) from exc


@router.get("/customers")
def customers():
    return [c.model_dump(mode="json") for c in MockStore.load().fixture.customers]


@router.post("/sessions")
def sign_in(
    request: DemoSignIn, repo: Annotated[SupportRepository, Depends(repository)]
):
    try:
        return {
            "token": str(repo.sign_in(MockStore.load(), request.customer_id)),
            "demo_only": True,
        }
    except (ValueError, SQLAlchemyError) as exc:
        error(exc)


@router.post("/conversations")
def new_conversation(
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
):
    try:
        return {"conversation_id": str(repo.create_conversation(token))}
    except (LookupError, SQLAlchemyError) as exc:
        error(exc)


@router.get("/conversations")
def conversations(
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
):
    try:
        return repo.conversations(token)
    except (LookupError, SQLAlchemyError) as exc:
        error(exc)


@router.get("/conversations/{conversation_id}")
def history(
    conversation_id: UUID,
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
):
    try:
        return repo.history(token, conversation_id)
    except (LookupError, SQLAlchemyError) as exc:
        error(exc)


async def execute(
    repo,
    token,
    conversation_id,
    request,
    run_id,
    customer_id,
    context,
    deps,
    on_step=None,
):
    saved_steps = []
    checkpoint = None

    def capture(step):
        saved_steps.append(step)
        if on_step and step.stage != "stop":
            on_step(step)

    with logfire.span("Customer support {run_id}", run_id=str(run_id)) as span:
        trace_context = span.get_span_context()
        trace_id = (
            f"{trace_context.trace_id:032x}"
            if EXPORT_ENABLED and trace_context is not None and trace_context.is_valid
            else None
        )
        try:
            repo.attach_trace(token, conversation_id, run_id, trace_id)
            checkpoint, resumed = repo.task_for_message(
                token, conversation_id, run_id, request.message
            )
            if checkpoint:
                context = [
                    *context,
                    ConversationTurn(
                        question=checkpoint.goal,
                        answer=checkpoint.last_answer,
                        order_ids=checkpoint.selected_order_ids,
                        proposal_ids=(checkpoint.pending_proposal_id,)
                        if checkpoint.pending_proposal_id
                        else (),
                    ),
                ]
            result = await run_support(
                SupportRequest(
                    conversation_id=str(conversation_id), message=request.message
                ),
                deps.store,
                repo.customer_store(deps.store, customer_id),
                deps.model,
                deps.judge,
                deps.index,
                deps.embedder,
                str(run_id),
                context,
                capture,
                operations_enabled=True,
                case_lookup=lambda key: repo.case(token, conversation_id, key),
                pending_ids=repo.pending(token, conversation_id),
                task_checkpoint=checkpoint,
                task_resumed=resumed,
            )
            result = result.model_copy(update={"task": checkpoint})
        except BaseException:
            interrupted = SupportStep(
                sequence=len(saved_steps) + 1,
                stage="stop",
                details={"reason": "interrupted", "disposition": "handoff_needed"},
            )
            result = SupportResponse(
                run_id=str(run_id),
                conversation_id=str(conversation_id),
                disposition="handoff_needed",
                answer="The support check was interrupted. Please retry.",
                stop_reason="interrupted",
                steps=(*saved_steps, interrupted),
                fixture_version=deps.store.fixture.version,
                task=checkpoint,
            )
            repo.finish(token, conversation_id, request.message, result)
            raise
        try:
            result = repo.finish(
                token, conversation_id, request.message, result, deps.store
            )
        except (SQLAlchemyError, RuntimeError, ValueError):
            repo.abort(token, conversation_id, run_id)
            raise
        if on_step:
            emitted = len([step for step in saved_steps if step.stage != "stop"])
            for step in result.steps[emitted:]:
                on_step(step)
        return result


@router.post(
    "/conversations/{conversation_id}/messages", response_model=SupportResponse
)
async def message(
    conversation_id: UUID,
    request: MessageRequest,
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
    deps: Annotated[Runtime, Depends(runtime)],
):
    try:
        run_id, customer_id, context = repo.begin(token, conversation_id)
        return await execute(
            repo, token, conversation_id, request, run_id, customer_id, context, deps
        )
    except (LookupError, ValueError, TypeError, SQLAlchemyError) as exc:
        error(exc)


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream(
    conversation_id: UUID,
    request: MessageRequest,
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
    deps: Annotated[Runtime, Depends(runtime)],
):
    try:
        run_id, customer_id, context = repo.begin(token, conversation_id)
    except (LookupError, ValueError, TypeError, SQLAlchemyError) as exc:
        error(exc)
    queue = asyncio.Queue()

    def on_step(step: SupportStep):
        queue.put_nowait({"type": "step", "step": step.model_dump(mode="json")})

    async def work():
        try:
            result = await execute(
                repo,
                token,
                conversation_id,
                request,
                run_id,
                customer_id,
                context,
                deps,
                on_step,
            )
            queue.put_nowait(
                {"type": "completed", "result": result.model_dump(mode="json")}
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - terminal stream error must be visible
            queue.put_nowait(
                {"type": "error", "message": "Support run or persistence failed"}
            )

    async def events():
        task = asyncio.create_task(work())
        try:
            yield (
                "data: "
                + json.dumps({"type": "started", "run_id": str(run_id)})
                + "\n\n"
            )
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield "data: " + json.dumps(event) + "\n\n"
                if event["type"] in {"completed", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@router.post(
    "/conversations/{conversation_id}/proposals/{proposal_id}/decision",
    response_model=SupportResponse,
)
def decide(
    conversation_id: UUID,
    proposal_id: UUID,
    request: ConfirmationRequest,
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
):
    from .actions import confirm

    try:
        return confirm(
            repo, token, conversation_id, proposal_id, request, MockStore.load()
        )
    except (LookupError, ValueError, TypeError, SQLAlchemyError) as exc:
        error(exc)


@router.get("/conversations/{conversation_id}/cases")
def cases(
    conversation_id: UUID,
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
):
    try:
        return repo.cases(token, conversation_id)
    except (LookupError, SQLAlchemyError) as exc:
        error(exc)


@router.get("/conversations/{conversation_id}/cases/{case_id}")
def case_detail(
    conversation_id: UUID,
    case_id: str,
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
):
    try:
        case = repo.case(token, conversation_id, case_id)
        if case is None:
            raise LookupError("Case not found")
        return case
    except (LookupError, ValueError, TypeError, SQLAlchemyError) as exc:
        error(exc)


@router.post(
    "/conversations/{conversation_id}/runs/{run_id}/replay",
    response_model=SupportResponse,
)
def replay_operation(
    conversation_id: UUID,
    run_id: UUID,
    token: Annotated[UUID, Depends(session_token)],
    repo: Annotated[SupportRepository, Depends(repository)],
):
    """Retry a known server-issued operation by returning its committed result."""
    try:
        return repo.saved_result(token, conversation_id, run_id)
    except (LookupError, SQLAlchemyError) as exc:
        error(exc)
