from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import select

from backend.db import db_utils, schemas

load_dotenv(override=True, dotenv_path="backend/.env")
client = OpenAI()


def retrieve_document_by_distance(
    query: str,
    symbol: str,
    document_type: schemas.DocumentType,
    top_n: int = 3,
    published_after: datetime | None = None,
):
    response = client.embeddings.create(input=query, model="text-embedding-3-small")
    query_embedding = response.data[0].embedding

    distance = schemas.DocumentChunk.embedding.cosine_distance(query_embedding)
    statement = (
        select(
            schemas.DocumentChunk,
            schemas.Document,
            distance.label("distance"),
        )
        .join(
            schemas.Document, schemas.DocumentChunk.document_id == schemas.Document.id
        )
        .where(
            schemas.DocumentChunk.embedding.is_not(None),
            schemas.Document.document_type == document_type,
            schemas.Document.filter_metadata["symbol"].as_string() == symbol,
        )
        .order_by(distance)
        .limit(top_n)
    )
    if published_after is not None:
        statement = statement.where(schemas.Document.published_at >= published_after)

    with db_utils.get_session() as session:
        rows = session.execute(statement).all()

        return [
            {
                "chunk_id": str(chunk.id),
                "reference_id": str(document.reference_id),
                "chunk_index": str(chunk.chunk_index),
                "document_id": str(document.id),
                "content": chunk.content,
                "similarity": 1 - distance_value,
                "title": document.title,
                "source_url": document.source_url,
                "published_at": document.published_at,
            }
            for chunk, document, distance_value in rows
        ]
