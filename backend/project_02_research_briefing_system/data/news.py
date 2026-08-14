import os
from typing import Any

import requests
from dateutil import parser
from dotenv import load_dotenv

from backend.db import db_utils, schemas
from backend.shared.embeddings import (
    check_should_embed,
    embed_document_in_chunks,
    insert_document,
    insert_document_chunks,
    serialize_document,
)

load_dotenv()


def fetch_news(
    symbol: str,
    query: str,
    from_date: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Fetch and normalize news articles without writing to the database."""
    api_key = os.getenv("GNEWS_API_KEY")
    if not api_key:
        raise ValueError("Missing api key!")
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")

    q = f"{symbol}, {query}, news"
    date = parser.parse(from_date)
    iso_from = date.isoformat()

    response = requests.get(
        "https://gnews.io/api/v4/top-headlines",
        params={
            "q": q,
            "lang": "en",
            "max": limit,
            "from": iso_from,
            "apikey": api_key,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    articles = data.get("articles")
    if not isinstance(articles, list):
        raise ValueError("GNews response did not contain an articles list")

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
) -> list[dict[str, Any]]:
    """Fetch, embed, and persist news articles for later retrieval."""
    articles = fetch_news(
        symbol=symbol,
        query=query,
        from_date=from_date,
        limit=limit,
    )

    with db_utils.get_session() as session:
        # Embed and save articles for future use
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
                metadata={"symbol": symbol},
            )

            should_embed = check_should_embed(session, doc_uuid)
            if should_embed:
                if not article["content"]:
                    raise ValueError(
                        f"Article {article['reference_id']} has no content to embed"
                    )
                chunks = embed_document_in_chunks(article["content"], doc_uuid)
                created_chunks = insert_document_chunks(session, chunks, doc_uuid)
            else:
                created_chunks = (
                    session.query(schemas.DocumentChunk)
                    .filter_by(document_id=doc_uuid)
                    .all()
                )

            doc = session.get(schemas.Document, doc_uuid)
            if doc is None:
                raise RuntimeError(f"Document {doc_uuid} was not found after insertion")
            serialized_articles.append(
                serialize_document(doc, created_chunks, source="gnews")
            )

    return serialized_articles
