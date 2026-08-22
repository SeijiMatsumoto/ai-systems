import os
from datetime import datetime, timedelta, timezone
from typing import Any

import logfire
import requests
from dateutil import parser
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.db import db_utils, schemas
from backend.shared.article_processing import (
    ARTICLE_CLEANING_VERSION,
    MIN_ARTICLE_TEXT_CHARS,
    clean_article_text,
    story_fingerprint,
    story_key,
)
from backend.shared.embeddings import (
    check_should_embed,
    embed_document_in_chunks,
    insert_document,
    insert_document_chunks,
    serialize_document,
)

load_dotenv()


class WorldNewsTransientError(RuntimeError):
    """A retryable World News API transport, rate-limit, or server failure."""


def _build_world_news_query(
    symbol: str,
    query: str,
    company_name: str | None = None,
) -> str:
    normalized_query = " ".join(query.split())
    if not normalized_query:
        raise ValueError("query must not be blank")

    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol must not be blank")
    company_scope = normalized_symbol
    if company_name:
        escaped_company_name = company_name.strip().replace('"', "")
        company_scope = f'({normalized_symbol} OR "{escaped_company_name}")'

    world_news_query = f"{company_scope} AND ({normalized_query})"
    if len(world_news_query) > 100:
        raise ValueError(
            "World News API query must be at most 100 characters after company scoping"
        )
    return world_news_query


@retry(
    retry=retry_if_exception_type(WorldNewsTransientError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def fetch_news(
    symbol: str,
    query: str,
    from_date: str,
    limit: int = 5,
    company_name: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch and normalize news articles without writing to the database."""
    api_key = os.getenv("WORLD_NEWS_API_KEY")
    if not api_key:
        raise ValueError("WORLD_NEWS_API_KEY is not configured")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    q = _build_world_news_query(symbol, query, company_name)
    date = parser.parse(from_date)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    else:
        date = date.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)

    if date > now:
        raise ValueError("from_date cannot be in the future")

    age = now - date
    if age > timedelta(days=30):
        raise ValueError("from_date cannot be older than 30 days on the free plan")

    date_from = date.strftime("%Y-%m-%d %H:%M:%S")

    with logfire.span(
        "Fetching World News API articles for {symbol}",
        symbol=symbol.upper(),
        query=query,
        world_news_query=q,
        from_date=date_from,
        limit=limit,
    ):
        try:
            response = requests.get(
                "https://api.worldnewsapi.com/search-news",
                headers={"x-api-key": api_key},
                params={
                    "text": q,
                    "text-match-indexes": "title,content",
                    "language": "en",
                    "earliest-publish-date": date_from,
                    "sort": "publish-time",
                    "sort-direction": "DESC",
                    "number": limit,
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise WorldNewsTransientError(
                f"World News API request failed with {type(exc).__name__}"
            ) from None

        if response.status_code == 429 or response.status_code >= 500:
            raise WorldNewsTransientError(
                "World News API temporarily unavailable with "
                f"status {response.status_code}"
            )
        if not response.ok:
            logfire.error(
                "World News API request failed for {symbol} with status {status_code}",
                symbol=symbol.upper(),
                status_code=response.status_code,
            )
            raise RuntimeError(
                f"World News API returned {response.status_code}: {response.text[:500]}"
            )

        data = response.json()

    if not isinstance(data, dict):
        raise TypeError("World News API response was not an object")
    articles = data.get("news")
    if not isinstance(articles, list):
        raise TypeError("World News API response did not contain a news list")

    if not articles:
        logfire.warn(
            "World News API returned no articles for {symbol}",
            symbol=symbol.upper(),
            query=query,
            from_date=date_from,
        )
    else:
        logfire.info(
            "World News API returned {article_count} articles for {symbol}",
            article_count=len(articles),
            available_articles=data.get("available"),
            symbol=symbol.upper(),
            quota_request=response.headers.get("X-API-Quota-Request"),
            quota_left=response.headers.get("X-API-Quota-Left"),
        )

    normalized_articles: list[dict[str, Any]] = []
    skipped_articles = 0
    skipped_duplicate_articles = 0
    seen_story_keys: set[str] = set()
    for article in articles:
        if not isinstance(article, dict):
            skipped_articles += 1
            continue
        content = article.get("text")
        title = article.get("title")
        source_url = article.get("url")
        published_at = article.get("publish_date")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (content, title, source_url, published_at)
        ):
            skipped_articles += 1
            continue
        assert isinstance(content, str)
        assert isinstance(title, str)
        assert isinstance(source_url, str)
        assert isinstance(published_at, str)

        normalized_story_key = story_key(title)
        if normalized_story_key in seen_story_keys:
            skipped_duplicate_articles += 1
            continue

        cleaned_content = clean_article_text(title, content)
        if len(cleaned_content) < MIN_ARTICLE_TEXT_CHARS:
            skipped_articles += 1
            continue
        seen_story_keys.add(normalized_story_key)

        authors = article.get("authors")
        author = (
            ", ".join(str(value) for value in authors if value)
            if isinstance(authors, list)
            else None
        )
        normalized_articles.append(
            {
                "reference_id": str(article.get("id") or source_url),
                "title": title.strip(),
                "source_url": source_url.strip(),
                "author": author or None,
                "published_at": published_at,
                "content": cleaned_content,
                "raw_content_chars": len(content.strip()),
                "cleaned_content_chars": len(cleaned_content),
                "story_fingerprint": story_fingerprint(title),
            }
        )

    if skipped_articles:
        logfire.warn(
            "Skipped {skipped_articles} World News API articles without full text or required metadata",
            skipped_articles=skipped_articles,
            symbol=symbol.upper(),
        )
    if skipped_duplicate_articles:
        logfire.info(
            "Skipped {skipped_duplicate_articles} duplicate World News API stories",
            skipped_duplicate_articles=skipped_duplicate_articles,
            symbol=symbol.upper(),
        )

    return normalized_articles


def ingest_news(
    symbol: str,
    query: str,
    from_date: str,
    limit: int = 5,
    company_name: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch, embed, and persist news articles for later retrieval."""
    with logfire.span(
        "Ingesting World News API articles for {symbol}",
        symbol=symbol.upper(),
        query=query,
        from_date=from_date,
        limit=limit,
    ):
        articles = fetch_news(
            symbol=symbol,
            query=query,
            from_date=from_date,
            limit=limit,
            company_name=company_name,
        )

        embedded_documents = 0
        skipped_duplicate_articles = 0
        with db_utils.get_session() as session:
            serialized_articles = []
            existing_documents = (
                session.query(schemas.Document)
                .filter(
                    schemas.Document.document_type == schemas.DocumentType.ARTICLE,
                    schemas.Document.filter_metadata["symbol"].as_string()
                    == symbol.strip().upper(),
                    schemas.Document.filter_metadata["content_quality"].as_string()
                    == "full_text",
                )
                .order_by(schemas.Document.created_at, schemas.Document.id)
                .all()
            )
            existing_by_reference = {
                document.reference_id: document for document in existing_documents
            }
            existing_story_owners: dict[str, schemas.Document] = {}
            for document in existing_documents:
                existing_story_owners.setdefault(story_key(document.title), document)

            for article in articles:
                reference_id = str(article["reference_id"])
                normalized_story_key = story_key(str(article["title"]))
                existing_document = existing_by_reference.get(reference_id)
                story_owner = existing_story_owners.get(normalized_story_key)
                if story_owner is not None and story_owner.id != getattr(
                    existing_document, "id", None
                ):
                    skipped_duplicate_articles += 1
                    continue

                metadata = {
                    "symbol": symbol.strip().upper(),
                    "content_quality": "full_text",
                    "provider": "world_news_api",
                    "story_fingerprint": article["story_fingerprint"],
                    "cleaning_version": ARTICLE_CLEANING_VERSION,
                    "raw_content_chars": article["raw_content_chars"],
                    "cleaned_content_chars": article["cleaned_content_chars"],
                }
                previous_metadata: dict[str, Any] = {}
                if existing_document is None:
                    doc_uuid = insert_document(
                        session,
                        document_type=schemas.DocumentType.ARTICLE,
                        reference_id=reference_id,
                        title=str(article["title"]),
                        source_url=str(article["source_url"]),
                        author=(str(article["author"]) if article["author"] else None),
                        published_at=str(article["published_at"]),
                        metadata=metadata,
                    )
                    doc = session.get(schemas.Document, doc_uuid)
                    if doc is None:
                        raise RuntimeError(
                            f"Document {doc_uuid} was not found after insertion"
                        )
                    existing_by_reference[reference_id] = doc
                    existing_story_owners[normalized_story_key] = doc
                else:
                    doc = existing_document
                    doc_uuid = doc.id
                    doc.title = str(article["title"])
                    doc.source_url = str(article["source_url"])
                    doc.author = str(article["author"]) if article["author"] else None
                    doc.published_at = parser.parse(str(article["published_at"]))
                    previous_metadata = doc.filter_metadata or {}
                    doc.filter_metadata = metadata

                needs_clean_reembedding = (
                    existing_document is not None
                    and previous_metadata.get("cleaning_version")
                    != ARTICLE_CLEANING_VERSION
                )
                should_embed = needs_clean_reembedding or check_should_embed(
                    session, doc_uuid
                )
                if should_embed:
                    chunks = embed_document_in_chunks(str(article["content"]), doc_uuid)
                    if needs_clean_reembedding:
                        (
                            session.query(schemas.DocumentChunk)
                            .filter_by(document_id=doc_uuid)
                            .delete(synchronize_session=False)
                        )
                    created_chunks = insert_document_chunks(session, chunks, doc_uuid)
                    embedded_documents += 1
                else:
                    created_chunks = (
                        session.query(schemas.DocumentChunk)
                        .filter_by(document_id=doc_uuid)
                        .all()
                    )

                serialized_articles.append(
                    serialize_document(doc, created_chunks, source="world_news_api")
                )

        logfire.info(
            "Completed World News API ingestion for {symbol}: {document_count} documents",
            symbol=symbol.upper(),
            document_count=len(serialized_articles),
            embedded_documents=embedded_documents,
            reused_documents=len(serialized_articles) - embedded_documents,
            skipped_duplicate_articles=skipped_duplicate_articles,
            query=query,
            from_date=from_date,
        )

        return serialized_articles
