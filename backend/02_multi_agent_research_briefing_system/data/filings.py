import json
from datetime import datetime

import redis
from edgar import Company, set_identity

from backend.db import db_utils
from backend.db.schemas import DocumentType
from backend.shared.embeddings import (
    embed_document_in_chunks,
    get_document_and_chunks,
    insert_document,
    insert_document_chunks,
    serialize_document,
)

set_identity("Sage Matsumoto seijim27@gmail.com")


def get_latest_filing(symbol: str):
    this_month = datetime.today().strftime("%Y-%m")
    cache_key = f"filings-{symbol}-{this_month}"

    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    cached_data = r.get(cache_key)

    if cached_data:
        print("cache hit!")
        return json.loads(cached_data)

    try:
        company = Company(symbol)
        filing = company.get_filings(form="10-K")
        accession_no = filing.latest().accession_no

        with db_utils.get_session() as session:
            # check db for latest filing first
            document, chunks = get_document_and_chunks(
                session, document_id=accession_no, document_type=DocumentType.FILING
            )

            if document and chunks:
                print("Found existing filing in database.")
                serialized = serialize_document(document, chunks)
                r.set(
                    cache_key,
                    json.dumps(serialized),
                    ex=30 * 24 * 60 * 60,
                )  # Cache for 30 days
                return serialized

            metadata = {
                "document_type": DocumentType.FILING,
                "document_id": accession_no,
                "title": f"{filing.company_name} - {filing.latest().form} - {filing.latest().filing_date}",
                "source_url": filing.latest().url,
                "author": filing.company_name,
                "published_at": filing.latest().filing_date.isoformat(),
            }

            doc_id = insert_document(session, **metadata)
            chunks = embed_document_in_chunks(
                text=filing.latest().text(),
                doc_id=doc_id,
            )
            insert_document_chunks(session, chunks, doc_id)

            # load ORM objects to serialize within the same transaction
            from backend.db import schemas as _schemas

            doc = session.get(_schemas.Document, doc_id)
            created_chunks = (
                session.query(_schemas.DocumentChunk)
                .filter_by(document_id=doc.id)
                .all()
            )

            serialized = serialize_document(doc, created_chunks, source="edgar")

        r.set(
            cache_key, json.dumps(serialized), ex=30 * 24 * 60 * 60
        )  # Cache for 30 days

        return serialized
    except ValueError as e:
        print(f"Error! {e}")


print(get_latest_filing("AAPL"))
