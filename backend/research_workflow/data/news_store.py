import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from backend.db import db_utils, schemas
from backend.research_workflow.agent.evidence import split_passages
from backend.shared.article_processing import ARTICLE_CLEANING_VERSION


def _required_string(article: Mapping[str, Any], key: str) -> str:
    value = article.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"News article is missing {key}")
    return value.strip()


def _parse_published_at(value: object) -> datetime:
    if isinstance(value, datetime):
        published_at = value
    elif isinstance(value, str):
        try:
            published_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("News article has an invalid published_at value") from exc
    else:
        raise TypeError("News article is missing published_at")

    if published_at.tzinfo is None:
        return published_at.replace(tzinfo=timezone.utc)
    return published_at.astimezone(timezone.utc)


def persist_inspected_news_article(
    article: Mapping[str, Any],
    *,
    symbol: str,
) -> list[dict[str, Any]]:
    """Persist one inspected article and return DB-shaped rows for evidence ranking."""
    raw_reference_id = _required_string(article, "reference_id")
    reference_id = (
        raw_reference_id
        if raw_reference_id.startswith("world_news:")
        else f"world_news:{raw_reference_id}"
    )
    title = _required_string(article, "title")
    source_url = _required_string(article, "source_url")
    content = _required_string(article, "content")
    published_at = _parse_published_at(article.get("published_at"))
    author_value = article.get("author")
    author = str(author_value).strip() if author_value else None
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    normalized_symbol = symbol.strip().upper()

    with db_utils.get_session() as session:
        document = (
            session.query(schemas.Document)
            .filter(schemas.Document.reference_id == reference_id)
            .one_or_none()
        )

        metadata = {
            "symbol": normalized_symbol,
            "provider": "world_news_api",
            "content_quality": "full_text",
            "content_hash": content_hash,
            "cleaning_version": ARTICLE_CLEANING_VERSION,
            "persistence_mode": "inspect_on_demand",
        }

        if document is None:
            document = schemas.Document(
                document_type=schemas.DocumentType.ARTICLE,
                reference_id=reference_id,
                title=title,
                source_url=source_url,
                author=author,
                published_at=published_at,
                filter_metadata=metadata,
            )
            session.add(document)
            session.flush()
            existing_chunks: list[schemas.DocumentChunk] = []
            content_changed = True
        else:
            if document.document_type != schemas.DocumentType.ARTICLE:
                raise ValueError(
                    f"Reference {reference_id} belongs to a non-article document"
                )
            previous_metadata = document.filter_metadata or {}
            content_changed = previous_metadata.get("content_hash") != content_hash
            document.title = title
            document.source_url = source_url
            document.author = author
            document.published_at = published_at
            document.filter_metadata = {**previous_metadata, **metadata}
            existing_chunks = (
                session.query(schemas.DocumentChunk)
                .filter(schemas.DocumentChunk.document_id == document.id)
                .order_by(schemas.DocumentChunk.chunk_index)
                .all()
            )

        # Rebuild non-embedded passage chunks only when the article is new, changed,
        # or was previously stored without any chunks.
        if content_changed or not existing_chunks:
            for chunk in existing_chunks:
                session.delete(chunk)
            session.flush()

            chunk_metadata = {
                "symbol": normalized_symbol,
                "provider": "world_news_api",
                "content_quality": "full_text",
            }
            existing_chunks = [
                schemas.DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=passage,
                    embedding=None,
                    filter_metadata=chunk_metadata,
                )
                for index, (_, _, passage) in enumerate(split_passages(content))
                if passage.strip()
            ]
            session.add_all(existing_chunks)
            session.flush()

        return [
            {
                "chunk_id": str(chunk.id),
                "reference_id": document.reference_id,
                "chunk_index": chunk.chunk_index,
                "document_id": str(document.id),
                "document_type": schemas.DocumentType.ARTICLE.value,
                "content": chunk.content,
                "content_quality": "full_text",
                "similarity": 0.0,
                "title": document.title,
                "source_url": document.source_url,
                "published_at": document.published_at,
            }
            for chunk in existing_chunks
        ]
