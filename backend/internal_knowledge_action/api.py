"""HTTP preview and saved read-only answers for synthetic knowledge."""

import asyncio
import json
from contextlib import suppress
from typing import Any, Never
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from openai import OpenAIError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.db import db_utils
from backend.db.schemas import KnowledgeAnswerOutput, LlmRun
from backend.internal_knowledge_action.answer_service import run_answer
from backend.internal_knowledge_action.contracts import (
    DemoPersona,
    IndexBuildReport,
    IndexStatus,
    KnowledgeAnswerRequest,
    KnowledgeAnswerResult,
    KnowledgeAnswerSummary,
    KnowledgeStep,
    RetrievalPreview,
    RetrievalPreviewRequest,
)
from backend.internal_knowledge_action.embedding import (
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from backend.internal_knowledge_action.ingestion import (
    index_matches_fixture,
    ingest_fixture,
    load_fixture,
    load_index,
    save_index,
)
from backend.internal_knowledge_action.retrieval import (
    preview_retrieval,
)

router = APIRouter(
    prefix="/agent/internal_knowledge_action", tags=["knowledge-preview"]
)


@router.get("/personas", response_model=list[DemoPersona])
def list_demo_personas() -> list[DemoPersona]:
    return list(load_fixture().personas)


@router.get("/index-status", response_model=IndexStatus)
def get_index_status() -> IndexStatus:
    fixture = load_fixture()
    index = load_index()
    return IndexStatus(
        ready=index is not None and index_matches_fixture(index, fixture),
        fixture_version=fixture.version,
        embedding_model=index.embedding_model if index else None,
        source_count=len(index.sources) if index else 0,
        chunk_count=len(index.chunks) if index else 0,
    )


@router.post("/index-fixture", response_model=IndexBuildReport)
def build_mock_index() -> IndexBuildReport:
    """Explicit local ingestion. This endpoint never calls a paid provider."""
    fixture = load_fixture()
    snapshot, report = ingest_fixture(fixture, MockEmbeddingProvider(), load_index())
    save_index(snapshot)
    return report


@router.post("/retrieval-preview", response_model=RetrievalPreview)
def retrieve_preview(request: RetrievalPreviewRequest) -> RetrievalPreview:
    fixture = load_fixture()
    index = load_index()
    if index is None or not index_matches_fixture(index, fixture):
        raise HTTPException(
            status_code=409, detail="Build or refresh the fixture index first"
        )
    try:
        embedder = (
            MockEmbeddingProvider()
            if index.embedding_model == MockEmbeddingProvider.model_id
            else OpenAIEmbeddingProvider()
            if index.embedding_model == OpenAIEmbeddingProvider.model_id
            else None
        )
        if embedder is None:
            raise HTTPException(
                status_code=409, detail="Unsupported indexed embedding model"
            )
        return preview_retrieval(request, fixture, index, embedder)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(
            status_code=503, detail="Embedding provider unavailable"
        ) from exc


def _history_schema_error(exc: SQLAlchemyError) -> Never:
    original = getattr(exc, "orig", None)
    if (
        getattr(original, "pgcode", None) == "42P01"
        or getattr(original, "sqlstate", None) == "42P01"
        or "no such table" in str(original).lower()
    ):
        raise HTTPException(
            status_code=503,
            detail="Knowledge run history is not set up. Apply database migration 007.",
        ) from exc
    raise exc


@router.get("/answers", response_model=list[KnowledgeAnswerSummary])
def list_answers(
    limit: int = Query(default=10, ge=1, le=50),
) -> list[KnowledgeAnswerSummary]:
    try:
        with db_utils.get_session() as session:
            rows = session.execute(
                select(KnowledgeAnswerOutput, LlmRun)
                .join(LlmRun, LlmRun.id == KnowledgeAnswerOutput.run_id)
                .order_by(KnowledgeAnswerOutput.created_at.desc())
                .limit(limit)
            ).all()
            return [
                KnowledgeAnswerSummary(
                    run_id=saved.run_id,
                    status=run.status,
                    stop_reason=saved.response_payload["stop_reason"],
                    persona_id=saved.response_payload["request"]["persona_id"],
                    question=saved.response_payload["request"]["question"],
                    created_at=saved.created_at,
                )
                for saved, run in rows
            ]
    except SQLAlchemyError as exc:
        _history_schema_error(exc)


@router.get("/answers/{run_id}", response_model=KnowledgeAnswerResult)
def get_answer(run_id: UUID) -> KnowledgeAnswerResult:
    try:
        with db_utils.get_session() as session:
            saved = session.get(KnowledgeAnswerOutput, run_id)
            if saved is None:
                raise HTTPException(status_code=404, detail="Knowledge run not found")
            return KnowledgeAnswerResult.model_validate(saved.response_payload)
    except SQLAlchemyError as exc:
        _history_schema_error(exc)


@router.post("/answer-stream")
async def stream_answer(request: KnowledgeAnswerRequest) -> StreamingResponse:
    async def events():
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        def on_step(step: KnowledgeStep) -> None:
            queue.put_nowait(("step", step.model_dump(mode="json")))

        async def run() -> None:
            try:
                result = await run_answer(request, on_step=on_step)
                await queue.put(("result", result.model_dump(mode="json")))
            except Exception as exc:  # noqa: BLE001 - stream needs a terminal event
                await queue.put(("error", {"detail": type(exc).__name__}))

        task = asyncio.create_task(run())
        try:
            while True:
                event_type, payload = await queue.get()
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                if event_type in {"result", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(events(), media_type="text/event-stream")
