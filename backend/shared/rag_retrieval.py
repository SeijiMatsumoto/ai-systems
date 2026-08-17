from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import and_, or_, select

from backend.db import db_utils, schemas

load_dotenv(override=True, dotenv_path="backend/.env")
client = OpenAI()


def retrieve_document_by_distance(
    query: str,
    symbol: str,
    document_type: schemas.DocumentType,
    top_n: int = 3,
    published_before: datetime | None = None,
    published_after: datetime | None = None,
    neighbor_radius: int = 0,
):
    if (
        published_after is not None
        and published_before is not None
        and published_after > published_before
    ):
        raise ValueError("published_after must be on or before published_before")

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
    if published_before is not None:
        statement = statement.where(schemas.Document.published_at <= published_before)

    with db_utils.get_session() as session:
        seed_rows = session.execute(statement).all()
        rows_by_chunk = {
            chunk.id: (chunk, document, float(distance_value))
            for chunk, document, distance_value in seed_rows
        }

        if neighbor_radius > 0 and seed_rows:
            neighbor_conditions = [
                and_(
                    schemas.DocumentChunk.document_id == document.id,
                    schemas.DocumentChunk.chunk_index.between(
                        max(0, chunk.chunk_index - neighbor_radius),
                        chunk.chunk_index + neighbor_radius,
                    ),
                )
                for chunk, document, _ in seed_rows
            ]
            neighbor_statement = (
                select(schemas.DocumentChunk, schemas.Document)
                .join(
                    schemas.Document,
                    schemas.DocumentChunk.document_id == schemas.Document.id,
                )
                .where(or_(*neighbor_conditions))
            )
            for chunk, document in session.execute(neighbor_statement).all():
                if chunk.id in rows_by_chunk:
                    continue
                nearest_seed_distance = min(
                    float(distance_value)
                    for seed_chunk, seed_document, distance_value in seed_rows
                    if seed_document.id == document.id
                    and abs(seed_chunk.chunk_index - chunk.chunk_index)
                    <= neighbor_radius
                )
                rows_by_chunk[chunk.id] = (
                    chunk,
                    document,
                    nearest_seed_distance,
                )

        rows = sorted(rows_by_chunk.values(), key=lambda row: row[2])

        return [
            {
                "chunk_id": str(chunk.id),
                "reference_id": str(document.reference_id),
                "chunk_index": chunk.chunk_index,
                "document_id": str(document.id),
                "document_type": document.document_type.value,
                "content_quality": (document.filter_metadata or {}).get(
                    "content_quality"
                ),
                "content": chunk.content,
                "similarity": 1 - distance_value,
                "title": document.title,
                "source_url": document.source_url,
                "published_at": document.published_at,
            }
            for chunk, document, distance_value in rows
        ]
