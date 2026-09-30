"""Read-only HTTP preview for the synthetic knowledge access boundary."""

from fastapi import APIRouter, HTTPException
from openai import OpenAIError

from backend.internal_knowledge_action.contracts import (
    DemoPersona,
    IndexBuildReport,
    IndexStatus,
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
