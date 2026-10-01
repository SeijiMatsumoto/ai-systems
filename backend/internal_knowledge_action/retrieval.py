"""ACL-scoped hybrid retrieval over previously embedded, versioned chunks."""

import math
import re
from collections import Counter

from backend.internal_knowledge_action.contracts import (
    CandidateTrace,
    IndexSnapshot,
    KnowledgeQuestionRequest,
    RankedExcerpt,
    RetrievalFixture,
    RetrievalResult,
    RetrievalStep,
    SourceLocator,
)
from backend.internal_knowledge_action.embedding import STOP_WORDS, EmbeddingProvider

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
ACTION_WORDS = frozenset(
    {"assign", "create", "delete", "file", "open", "send", "update"}
)
MAX_CANDIDATES = 8
MAX_RESULTS = 3
MAX_EXCERPT_CHARS = 600
MIN_LEXICAL_TERMS = 2
MIN_VECTOR_COSINE = (
    0.35  # Calibrated for the richer mock fixture; evaluate before using a real model.
)


def normalize_question(question: str) -> str:
    normalized = " ".join(question.split())
    if not normalized or not TOKEN_PATTERN.search(normalized.lower()):
        raise ValueError("Question must contain searchable text")
    return normalized


def _terms(value: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(value.lower())
        if token not in STOP_WORDS
    ]


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("Query and indexed embeddings have different dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _excerpt_span(body: str, start: int, end: int) -> tuple[int, int]:
    """Give a ranked chunk its surrounding paragraph when it fits the context cap."""
    paragraph_start = body.rfind("\n\n", 0, start)
    paragraph_start = 0 if paragraph_start < 0 else paragraph_start + 2
    paragraph_end = body.find("\n\n", end)
    paragraph_end = len(body) if paragraph_end < 0 else paragraph_end
    if paragraph_end - paragraph_start > MAX_EXCERPT_CHARS:
        return start, end
    return paragraph_start, paragraph_end


def _lexical_scores(question: str, chunks: list) -> dict[str, tuple[float, int]]:
    """Small-corpus BM25 baseline; a production index would execute this in storage."""
    terms = set(_terms(question))
    if not terms or not chunks:
        return {}
    tokenized = {chunk.chunk_id: _terms(chunk.text) for chunk in chunks}
    document_frequency = Counter(
        token for tokens in tokenized.values() for token in set(tokens)
    )
    average_length = sum(len(tokens) for tokens in tokenized.values()) / len(chunks)
    scores: dict[str, tuple[float, int]] = {}
    for chunk in chunks:
        tokens = tokenized[chunk.chunk_id]
        frequency = Counter(tokens)
        matched = terms & frequency.keys()
        score = 0.0
        for token in matched:
            inverse_frequency = math.log(
                1
                + (len(chunks) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            count = frequency[token]
            score += (
                inverse_frequency
                * count
                * 2.2
                / (count + 1.2 * (0.25 + 0.75 * len(tokens) / average_length))
            )
        scores[chunk.chunk_id] = (score, len(matched))
    return scores


def retrieve_knowledge(
    request: KnowledgeQuestionRequest,
    fixture: RetrievalFixture,
    index: IndexSnapshot,
    embedder: EmbeddingProvider,
) -> RetrievalResult:
    normalized = normalize_question(request.question)
    persona = next(
        (item for item in fixture.personas if item.persona_id == request.persona_id),
        None,
    )
    if persona is None:
        raise LookupError("Unknown demo persona")
    if (
        index.fixture_version != fixture.version
        or index.embedding_model != embedder.model_id
    ):
        raise ValueError("Index version or embedding model does not match the fixture")

    signals = sorted(set(_terms(normalized)) & ACTION_WORDS)
    # ACL is resolved from server-owned metadata before either search path sees a chunk.
    authorized_sources = [
        source
        for source in index.sources
        if set(source.allowed_groups).intersection(persona.groups)
    ]
    authorized_ids = [source.source_id for source in authorized_sources]
    allowed = set(authorized_ids)
    chunks = [chunk for chunk in index.chunks if chunk.source_id in allowed]
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    source_by_id = {source.source_id: source for source in authorized_sources}
    fixture_sources = {source.source_id: source for source in fixture.sources}

    lexical_scores = _lexical_scores(normalized, chunks)
    lexical = sorted(
        (
            (chunk_id, score)
            for chunk_id, (score, matches) in lexical_scores.items()
            if matches >= MIN_LEXICAL_TERMS
        ),
        key=lambda item: (-item[1], item[0]),
    )[:MAX_CANDIDATES]
    query_vector = embedder.embed_query(normalized)
    vectors = sorted(
        (
            (chunk.chunk_id, score)
            for chunk in chunks
            if (score := _cosine(query_vector, chunk.embedding)) >= MIN_VECTOR_COSINE
        ),
        key=lambda item: (-item[1], item[0]),
    )[:MAX_CANDIDATES]
    lexical_rank = {chunk_id: rank for rank, (chunk_id, _) in enumerate(lexical, 1)}
    vector_rank = {chunk_id: rank for rank, (chunk_id, _) in enumerate(vectors, 1)}
    vector_score = dict(vectors)
    query_phrase = normalized.lower().strip("?!. ")

    # Reciprocal-rank fusion widens candidate recall; a bounded second stage
    # prefers exact phrases and stronger vector matches before context assembly.
    combined = []
    for chunk_id in lexical_rank.keys() | vector_rank.keys():
        chunk = chunk_by_id[chunk_id]
        fusion = sum(
            1 / (60 + rank)
            for rank in (lexical_rank.get(chunk_id), vector_rank.get(chunk_id))
            if rank
        )
        phrase_bonus = 0.01 if query_phrase in chunk.text.lower() else 0.0
        rerank = fusion + 0.01 * vector_score.get(chunk_id, 0.0) + phrase_bonus
        combined.append((chunk_id, rerank))
    combined.sort(key=lambda item: (-item[1], item[0]))
    selected = combined[:MAX_RESULTS]
    excerpts = []
    for chunk_id, score in selected:
        chunk = chunk_by_id[chunk_id]
        source = source_by_id[chunk.source_id]
        body = fixture_sources[chunk.source_id].body
        start, end = _excerpt_span(body, chunk.start, chunk.end)
        excerpts.append(
            RankedExcerpt(
                chunk_id=chunk_id,
                title=source.title,
                kind=source.kind,
                excerpt=body[start:end],
                locator=SourceLocator(
                    source_id=chunk.source_id,
                    revision=source.revision,
                    start=start,
                    end=end,
                ),
                lexical_rank=lexical_rank.get(chunk_id),
                vector_rank=vector_rank.get(chunk_id),
                rerank_score=round(score, 5),
            )
        )

    return RetrievalResult(
        fixture_version=fixture.version,
        embedding_model=index.embedding_model,
        persona_id=persona.persona_id,
        normalized_question=normalized,
        keyword_signals=signals,
        authorized_source_ids=authorized_ids,
        lexical_candidates=[
            CandidateTrace(
                chunk_id=chunk_id,
                source_id=chunk_by_id[chunk_id].source_id,
                rank=rank,
                score=round(score, 5),
            )
            for rank, (chunk_id, score) in enumerate(lexical, 1)
        ],
        vector_candidates=[
            CandidateTrace(
                chunk_id=chunk_id,
                source_id=chunk_by_id[chunk_id].source_id,
                rank=rank,
                score=round(score, 5),
            )
            for rank, (chunk_id, score) in enumerate(vectors, 1)
        ],
        ranked_excerpts=excerpts,
        steps=[
            RetrievalStep(
                stage="request_check",
                detail="Validated and normalized the question; recorded cheap action keyword signals.",
            ),
            RetrievalStep(
                stage="access_filter",
                detail="Resolved server-owned persona groups and limited both searches to authorized indexed chunks.",
                source_ids=authorized_ids,
            ),
            RetrievalStep(
                stage="lexical_search",
                detail="Scored authorized chunks with BM25-style term weighting.",
                source_ids=[chunk_by_id[item[0]].source_id for item in lexical],
            ),
            RetrievalStep(
                stage="vector_search",
                detail=f"Embedded the question with {embedder.model_id} and compared only authorized chunk vectors.",
                source_ids=[chunk_by_id[item[0]].source_id for item in vectors],
            ),
            RetrievalStep(
                stage="fusion_rerank",
                detail="Fused keyword and vector ranks, then applied a bounded deterministic rerank before context assembly.",
                source_ids=[item.locator.source_id for item in excerpts],
            ),
        ],
    )
