"""Versioned synthetic ingestion with idempotent chunk embedding and ACL updates."""

import hashlib
import math
import re
from pathlib import Path

from backend.internal_knowledge_action.contracts import (
    IndexBuildReport,
    IndexedChunk,
    IndexedSource,
    IndexSnapshot,
    RetrievalFixture,
    SourceRecord,
)
from backend.internal_knowledge_action.embedding import EmbeddingProvider

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "corpus_v3.json"
INDEX_PATH = Path(__file__).parent / "fixtures" / "knowledge_index.local"
MAX_CHUNK_CHARS = 180


def load_fixture(path: Path = FIXTURE_PATH) -> RetrievalFixture:
    fixture = RetrievalFixture.model_validate_json(path.read_text())
    source_ids = [source.source_id for source in fixture.sources]
    acl_ids = [rule.source_id for rule in fixture.acl]
    persona_ids = [persona.persona_id for persona in fixture.personas]
    if len(source_ids) != len(set(source_ids)) or len(acl_ids) != len(set(acl_ids)):
        raise ValueError("Fixture has duplicate source or ACL IDs")
    if set(source_ids) != set(acl_ids):
        raise ValueError("Every source must have exactly one ACL rule")
    if len(persona_ids) != len(set(persona_ids)):
        raise ValueError("Fixture has duplicate persona IDs")
    groups = {group for persona in fixture.personas for group in persona.groups}
    if not all(set(rule.allowed_groups) <= groups for rule in fixture.acl):
        raise ValueError("Fixture ACL refers to an unknown group")
    return fixture


def chunk_source(source: SourceRecord) -> list[tuple[str, int, int]]:
    """Group nearby sentences into bounded chunks with exact source offsets."""
    chunks: list[tuple[str, int, int]] = []
    group_start: int | None = None
    group_end = 0
    for match in re.finditer(r"[^.!?]+[.!?]?", source.body):
        start, end = match.span()
        while start < end and source.body[start].isspace():
            start += 1
        if start >= end:
            continue
        if group_start is not None and end - group_start > MAX_CHUNK_CHARS:
            chunks.append((source.body[group_start:group_end], group_start, group_end))
            group_start = None
        if end - start > MAX_CHUNK_CHARS:
            while end - start > MAX_CHUNK_CHARS:
                split = source.body.rfind(" ", start, start + MAX_CHUNK_CHARS + 1)
                if split <= start:
                    split = start + MAX_CHUNK_CHARS
                chunks.append((source.body[start:split], start, split))
                start = split
                while start < end and source.body[start].isspace():
                    start += 1
        if start < end:
            group_start = start if group_start is None else group_start
            group_end = end
    if group_start is not None:
        chunks.append((source.body[group_start:group_end], group_start, group_end))
    return chunks


def _hash(source: SourceRecord) -> str:
    return hashlib.sha256(f"{source.title}\0{source.body}".encode()).hexdigest()


def index_matches_fixture(index: IndexSnapshot, fixture: RetrievalFixture) -> bool:
    if index.fixture_version != fixture.version:
        return False
    access = {rule.source_id: rule.allowed_groups for rule in fixture.acl}
    indexed = {source.source_id: source for source in index.sources}
    return set(indexed) == {source.source_id for source in fixture.sources} and all(
        (item := indexed[source.source_id]).revision == source.revision
        and item.content_hash == _hash(source)
        and item.allowed_groups == access[source.source_id]
        for source in fixture.sources
    )


def ingest_fixture(
    fixture: RetrievalFixture,
    embedder: EmbeddingProvider,
    previous: IndexSnapshot | None = None,
) -> tuple[IndexSnapshot, IndexBuildReport]:
    if previous and (
        previous.fixture_version != fixture.version
        or previous.embedding_model != embedder.model_id
    ):
        previous = None
    prior_sources = (
        {source.source_id: source for source in previous.sources} if previous else {}
    )
    prior_chunks = (
        {chunk.source_id: [] for chunk in previous.chunks} if previous else {}
    )
    if previous:
        for chunk in previous.chunks:
            prior_chunks[chunk.source_id].append(chunk)
    access = {rule.source_id: rule.allowed_groups for rule in fixture.acl}
    sources: list[IndexedSource] = []
    chunks: list[IndexedChunk] = []
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    acl_only: list[str] = []
    pending: list[tuple[SourceRecord, list[tuple[str, int, int]]]] = []
    for source in fixture.sources:
        content_hash = _hash(source)
        old = prior_sources.get(source.source_id)
        sources.append(
            IndexedSource(
                source_id=source.source_id,
                kind=source.kind,
                title=source.title,
                revision=source.revision,
                content_hash=content_hash,
                allowed_groups=access[source.source_id],
            )
        )
        if old and old.content_hash == content_hash and old.revision == source.revision:
            chunks.extend(prior_chunks[source.source_id])
            if old.allowed_groups == access[source.source_id]:
                unchanged.append(source.source_id)
            else:
                acl_only.append(source.source_id)
            continue
        (updated if old else added).append(source.source_id)
        pending.append((source, chunk_source(source)))

    texts = [
        f"{source.title}\n{text}" for source, spans in pending for text, _, _ in spans
    ]
    vectors = embedder.embed_documents(texts) if texts else []
    if len(vectors) != len(texts):
        raise ValueError("Embedding provider returned the wrong number of vectors")
    if vectors and (
        any(len(vector) != len(vectors[0]) for vector in vectors)
        or any(not math.isfinite(value) for vector in vectors for value in vector)
    ):
        raise ValueError("Embedding provider returned invalid vectors")
    vector_index = 0
    for source, spans in pending:
        for index, (text, start, end) in enumerate(spans):
            chunks.append(
                IndexedChunk(
                    chunk_id=f"{source.source_id}@{source.revision}#{index}",
                    source_id=source.source_id,
                    text=text,
                    start=start,
                    end=end,
                    embedding=vectors[vector_index],
                )
            )
            vector_index += 1
    removed = sorted(
        set(prior_sources) - {source.source_id for source in fixture.sources}
    )
    snapshot = IndexSnapshot(
        fixture_version=fixture.version,
        embedding_model=embedder.model_id,
        sources=tuple(sources),
        chunks=tuple(chunks),
    )
    report = IndexBuildReport(
        fixture_version=fixture.version,
        embedding_model=embedder.model_id,
        added_sources=added,
        updated_sources=updated,
        unchanged_sources=unchanged,
        removed_sources=removed,
        acl_only_sources=acl_only,
        embedded_chunks=len(vectors),
        total_chunks=len(chunks),
    )
    return snapshot, report


def load_index(path: Path = INDEX_PATH) -> IndexSnapshot | None:
    if not path.exists():
        return None
    return IndexSnapshot.model_validate_json(path.read_text())


def save_index(snapshot: IndexSnapshot, path: Path = INDEX_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(snapshot.model_dump_json())
    temporary.replace(path)
