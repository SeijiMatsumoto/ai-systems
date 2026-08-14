import json
from datetime import date, datetime
from typing import Any

import redis
from edgar import Company, set_identity
from edgar.entity import EntityFiling, EntityFilings

from backend.db import db_utils, schemas
from backend.shared.embeddings import (
    embed_document_in_chunks,
    get_document_and_chunks,
    insert_document,
    insert_document_chunks,
    serialize_document,
)

set_identity("Sage Matsumoto seijim27@gmail.com")

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


def fetch_filings(
    symbol: str,
    form_type: str = "10-K",
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Fetch and normalize SEC filings without writing to the database."""
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    filing_date = None
    if start_date or end_date:
        filing_date = (
            (start_date or date(1900, 1, 1)).isoformat(),
            (end_date or date.today()).isoformat(),
        )

    cache_key = ":".join(
        [
            "filings",
            symbol.upper(),
            form_type.upper(),
            start_date.isoformat() if start_date else "any-start",
            end_date.isoformat() if end_date else "any-end",
            str(limit),
            datetime.today().strftime("%Y-%m-%d"),
        ]
    )
    cached_data = r.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    company = Company(symbol)
    matching_filings = company.get_filings(
        form=form_type,
        filing_date=filing_date,
    )
    selected = matching_filings.latest(limit)
    if selected is None:
        return []

    filings: list[EntityFiling]
    if isinstance(selected, EntityFiling):
        filings = [selected]
    else:
        if isinstance(selected, EntityFilings):
            candidates = [selected[index] for index in range(len(selected))]
        elif isinstance(selected, list):
            candidates = selected
        else:
            raise TypeError("EDGAR latest filings response had an unexpected type")

        filings = []
        for candidate in candidates:
            if not isinstance(candidate, EntityFiling):
                raise TypeError("EDGAR latest filings contained an unexpected item")
            filings.append(candidate)
    normalized = [
        {
            "reference_id": filing.accession_no,
            "form_type": filing.form,
            "title": (
                f"{matching_filings.company_name} - {filing.form} - "
                f"{filing.filing_date}"
            ),
            "source_url": filing.url,
            "author": matching_filings.company_name,
            "published_at": filing.filing_date,
            "content": filing.text(),
        }
        for filing in filings
    ]

    r.set(cache_key, json.dumps(normalized), ex=24 * 60 * 60)
    return normalized


def ingest_filings(
    symbol: str,
    form_type: str = "10-K",
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Fetch, embed, and persist SEC filings for later retrieval."""
    filings = fetch_filings(
        symbol=symbol,
        form_type=form_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    serialized_filings = []
    with db_utils.get_session() as session:
        for filing in filings:
            document, chunks = get_document_and_chunks(
                session,
                reference_id=filing["reference_id"],
                document_type=schemas.DocumentType.FILING,
            )
            if document and chunks:
                serialized_filings.append(serialize_document(document, chunks))
                continue

            doc_id = insert_document(
                session,
                document_type=schemas.DocumentType.FILING,
                reference_id=filing["reference_id"],
                title=filing["title"],
                source_url=filing["source_url"],
                author=filing["author"],
                published_at=filing["published_at"],
                metadata={
                    "symbol": symbol.upper(),
                    "form_type": filing["form_type"],
                },
            )
            embedded_chunks = embed_document_in_chunks(
                text=filing["content"],
                doc_id=doc_id,
            )
            insert_document_chunks(session, embedded_chunks, doc_id)

            document = session.get(schemas.Document, doc_id)
            if document is None:
                raise RuntimeError(f"Document {doc_id} was not found after insertion")
            created_chunks = (
                session.query(schemas.DocumentChunk).filter_by(document_id=doc_id).all()
            )
            serialized_filings.append(
                serialize_document(document, created_chunks, source="edgar")
            )

    return serialized_filings
