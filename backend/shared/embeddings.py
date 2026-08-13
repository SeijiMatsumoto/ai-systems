from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from tiktoken import get_encoding

from backend.db import schemas

load_dotenv(override=True, dotenv_path="backend/.env")
client = OpenAI()


def chunk_text_by_tokens(
    text: str, chunk_size: int = 500, overlap: int = 50
) -> list[str]:
    tokenizer = get_encoding("cl100k_base")
    tokens = tokenizer.encode(text)

    chunks = []
    for i in range(0, len(tokens), chunk_size - overlap):
        chunk_tokens = tokens[i : i + chunk_size]
        chunks.append(tokenizer.decode(chunk_tokens))
    return chunks


def check_should_embed(session, doc_uuid: str):
    existing_chunks = (
        session.query(schemas.DocumentChunk).filter_by(document_id=doc_uuid).first()
    )

    return bool(not existing_chunks)


def embed_document_in_chunks(
    text: str, doc_id: str, chunk_size: int = 500, overlap: int = 50
) -> list[dict[str, Any]]:
    chunks = chunk_text_by_tokens(text, chunk_size=chunk_size, overlap=overlap)
    response = client.embeddings.create(input=chunks, model="text-embedding-3-small")
    records = []
    for idx, (chunk, data) in enumerate(zip(chunks, response.data)):
        records.append(
            {
                "id": f"{doc_id}#chunk-{idx}",
                "doc_id": doc_id,
                "chunk_index": idx,
                "text": chunk,
                "embedding": data.embedding,
            }
        )

    return records


def insert_document(
    session,
    document_type: schemas.DocumentType,
    reference_id: str,
    title: str,
    source_url: str,
    author: str,
    published_at: str,
    metadata: Any | None,
):
    existing_doc = (
        session.query(schemas.Document).filter_by(reference_id=reference_id).first()
    )

    if existing_doc:
        print(f"Document {reference_id} already exists.")
        return existing_doc.id

    doc = schemas.Document(
        document_type=document_type,
        reference_id=reference_id,
        title=title,
        source_url=source_url,
        author=author,
        published_at=published_at,
        filter_metadata=(metadata or {}),
    )
    session.add(doc)
    session.flush()

    print(f"Inserted document with ID: {doc.id}")
    return doc.id


def insert_document_chunks(
    session,
    chunks_data: list[dict[str, Any]],
    document_id: str,
) -> list[schemas.DocumentChunk] | None:
    chunks = [
        schemas.DocumentChunk(
            document_id=document_id,
            chunk_index=item["chunk_index"],
            content=item["text"],
            embedding=item["embedding"],
        )
        for item in chunks_data
    ]

    session.add_all(chunks)

    print(f"Inserted {len(chunks)} document chunks.")
    return chunks


def get_document_and_chunks(
    session, reference_id: str, document_type: schemas.DocumentType
) -> tuple[schemas.Document, list[schemas.DocumentChunk]] | None:
    document = (
        session.query(schemas.Document)
        .filter_by(reference_id=reference_id, document_type=document_type)
        .first()
    )
    if not document:
        return None, []

    chunks = (
        session.query(schemas.DocumentChunk).filter_by(document_id=document.id).all()
    )
    return document, chunks


def get_documents_by_type(
    session,
    document_type: schemas.DocumentType,
    from_date: datetime,
    metadata: Any = None,
) -> list[dict]:
    """Retrieve multiple documents and their chunks matching a type, date, and keyword."""
    query = session.query(schemas.Document).filter(
        schemas.Document.document_type == document_type,
        schemas.Document.published_at >= from_date,
    )

    if metadata:
        for key, value in metadata.items():
            query = query.filter(
                schemas.Document.filter_metadata[key].as_string() == str(value)
            )

    documents = query.all()

    results = []
    for doc in documents:
        chunks = (
            session.query(schemas.DocumentChunk).filter_by(document_id=doc.id).all()
        )
        results.append(serialize_document(doc, chunks))

    return results


def serialize_document(
    doc: schemas.Document,
    chunks: list[schemas.DocumentChunk] | None = None,
    source: str = "db",
) -> dict:
    """Serialize a Document and optional chunks into a JSON-safe dict."""
    out = {
        "id": str(doc.id),
        "reference_id": doc.reference_id,
        "document_type": doc.document_type.value
        if hasattr(doc.document_type, "value")
        else str(doc.document_type),
        "title": doc.title,
        "source_url": doc.source_url,
        "author": doc.author,
        "published_at": doc.published_at.isoformat() if doc.published_at else None,
        "source": source,
    }
    if chunks is not None:
        out["chunks"] = [
            {"chunk_index": c.chunk_index, "content": c.content} for c in chunks
        ]
    return out
