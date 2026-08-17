import os
import re
from datetime import timezone
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
from backend.shared.embeddings import (
    check_should_embed,
    embed_document_in_chunks,
    insert_document,
    insert_document_chunks,
    serialize_document,
)

load_dotenv()


class GNewsTransientError(RuntimeError):
    """A retryable GNews transport, rate-limit, or server failure."""


def _build_gnews_query(
    symbol: str,
    query: str,
    company_name: str | None = None,
) -> str:
    normalized_query = " ".join(query.split())
    has_explicit_syntax = bool(
        re.search(r'\b(?:AND|OR|NOT)\b|["()]', normalized_query, flags=re.IGNORECASE)
    )

    if has_explicit_syntax:
        topic_query = normalized_query
    else:
        topic_query = " OR ".join(normalized_query.split())

    normalized_symbol = symbol.strip().upper()
    company_scope = normalized_symbol
    if company_name:
        escaped_company_name = company_name.strip().replace('"', "")
        company_scope = f'({normalized_symbol} OR "{escaped_company_name}")'

    return f"{company_scope} AND ({topic_query})"


@retry(
    retry=retry_if_exception_type(GNewsTransientError),
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
    api_key = os.getenv("GNEWS_API_KEY")
    if not api_key:
        raise ValueError("Missing api key!")
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")

    q = _build_gnews_query(symbol, query, company_name)
    date = parser.parse(from_date)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)

    iso_from = date.isoformat().replace("+00:00", "Z")

    with logfire.span(
        "Fetching GNews articles for {symbol}",
        symbol=symbol.upper(),
        query=query,
        gnews_query=q,
        from_date=iso_from,
        limit=limit,
    ):
        try:
            response = requests.get(
                "https://gnews.io/api/v4/search",
                params={
                    "q": q,
                    "lang": "en",
                    "max": limit,
                    "from": iso_from,
                    "apikey": api_key,
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise GNewsTransientError(
                f"GNews request failed with {type(exc).__name__}"
            ) from None

        if response.status_code == 429 or response.status_code >= 500:
            raise GNewsTransientError(
                f"GNews temporarily unavailable with status {response.status_code}"
            )
        if not response.ok:
            logfire.error(
                "GNews request failed for {symbol} with status {status_code}",
                symbol=symbol.upper(),
                status_code=response.status_code,
            )
            raise RuntimeError(
                f"GNews returned {response.status_code}: {response.text[:500]}"
            )

        data = response.json()

    articles = data.get("articles")
    if not isinstance(articles, list):
        raise TypeError("GNews response did not contain an articles list")

    if not articles:
        logfire.warn(
            "GNews returned no articles for {symbol}",
            symbol=symbol.upper(),
            query=query,
            from_date=iso_from,
        )
    else:
        logfire.info(
            "GNews returned {article_count} articles for {symbol}",
            article_count=len(articles),
            total_articles=data.get("totalArticles"),
            symbol=symbol.upper(),
        )

    return [
        {
            "reference_id": article.get("id") or article["url"],
            "title": article["title"],
            "source_url": article["url"],
            "author": article["source"]["name"],
            "published_at": article["publishedAt"],
            "content": article.get("content") or "",
        }
        for article in articles
    ]


def ingest_news(
    symbol: str,
    query: str,
    from_date: str,
    limit: int = 5,
    company_name: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch, embed, and persist news articles for later retrieval."""
    with logfire.span(
        "Ingesting GNews articles for {symbol}",
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
        with db_utils.get_session() as session:
            serialized_articles = []
            for article in articles:
                doc_uuid = insert_document(
                    session,
                    document_type=schemas.DocumentType.ARTICLE,
                    reference_id=article["reference_id"],
                    title=article["title"],
                    source_url=article["source_url"],
                    author=article["author"],
                    published_at=article["published_at"],
                    metadata={
                        "symbol": symbol,
                        "content_quality": "snippet",
                    },
                )

                should_embed = check_should_embed(session, doc_uuid)
                if should_embed:
                    if not article["content"]:
                        raise ValueError(
                            f"Article {article['reference_id']} has no content to embed"
                        )
                    chunks = embed_document_in_chunks(article["content"], doc_uuid)
                    created_chunks = insert_document_chunks(session, chunks, doc_uuid)
                    embedded_documents += 1
                else:
                    created_chunks = (
                        session.query(schemas.DocumentChunk)
                        .filter_by(document_id=doc_uuid)
                        .all()
                    )

                doc = session.get(schemas.Document, doc_uuid)
                if doc is None:
                    raise RuntimeError(
                        f"Document {doc_uuid} was not found after insertion"
                    )
                serialized_articles.append(
                    serialize_document(doc, created_chunks, source="gnews")
                )

        logfire.info(
            "Completed GNews ingestion for {symbol}: {document_count} documents",
            symbol=symbol.upper(),
            document_count=len(serialized_articles),
            embedded_documents=embedded_documents,
            reused_documents=len(serialized_articles) - embedded_documents,
            query=query,
            from_date=from_date,
        )

        return serialized_articles
