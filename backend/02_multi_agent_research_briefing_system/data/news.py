import os

import requests
from dateutil import parser
from dotenv import load_dotenv

from backend.db import db_utils, schemas
from backend.db.schemas import DocumentType
from backend.shared.embeddings import (
    check_should_embed,
    embed_document_in_chunks,
    get_documents_by_type,
    insert_document,
    insert_document_chunks,
    serialize_document,
)

load_dotenv()


def get_news_by_company(symbol: str, from_date: str):
    api_key = os.getenv("GNEWS_API_KEY")
    if not api_key:
        raise ValueError("Missing api key!")

    query = f"{symbol} news"
    limit = 5
    date = parser.parse(from_date)
    iso_from = date.isoformat()

    url = f"https://gnews.io/api/v4/top-headlines?q={query}&lang=en&max={limit}&from={iso_from}&apikey={api_key}"

    with db_utils.get_session() as session:
        # first we should check if news already exists from this date -
        existing_news = get_documents_by_type(
            session,
            document_type=DocumentType.ARTICLE,
            from_date=date,
            metadata={"symbol": symbol},
        )

        if len(existing_news) > 0:
            print("Existing news found!")
            return existing_news

        response = requests.get(url)
        data = response.json()
        articles = data["articles"]

        # Embed and save articles for future use
        serialized_articles = []
        for article in articles:
            reference_id = article["id"]
            doc_uuid = insert_document(
                session,
                document_type=schemas.DocumentType.ARTICLE,
                reference_id=reference_id,
                title=article["title"],
                source_url=article["url"],
                author=article["source"]["name"],
                published_at=article["publishedAt"],
                metadata={"symbol": symbol},
            )

            should_embed = check_should_embed(session, doc_uuid)
            if should_embed:
                chunks = embed_document_in_chunks(article["content"], doc_uuid)
                created_chunks = insert_document_chunks(session, chunks, doc_uuid)
            else:
                created_chunks = (
                    session.query(schemas.DocumentChunk)
                    .filter_by(document_id=doc_uuid)
                    .all()
                )

            doc = session.get(schemas.Document, doc_uuid)
            serialized_articles.append(
                serialize_document(doc, created_chunks, source="gnews")
            )

    return serialized_articles


print(get_news_by_company("AAPL", "2026-08-05"))
