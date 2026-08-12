"""Example script showing how to insert a Document and DocumentChunk using SQLAlchemy helpers.

This script intentionally does not create or connect to a DB if `DATABASE_URL` is unset —
it prints guidance instead. Set `DATABASE_URL` to a Postgres URL and run to perform the insert.
"""

import os
from pprint import pformat

from backend.db import db_utils, schemas


def insert_document_example():
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL is not set. Set it to a Postgres URL to run this example.")
        return None

    # Ensure tables exist (for local/dev only)
    db_utils.init_db()

    with db_utils.get_session() as session:
        doc = schemas.Document(
            title="Example Doc", source_url="https://example.com", author="copilot"
        )
        chunk = schemas.DocumentChunk(
            chunk_index=0,
            content="This is a chunk.",
            embedding=[0.1, 0.2, 0.3],
            filter_metadata={"lang": "en"},
        )
        doc.chunks.append(chunk)
        session.add(doc)
        # commit happens in context manager
        session.refresh(doc)

        print("Inserted document:")
        print(
            pformat({"id": str(doc.id), "title": doc.title, "chunks": len(doc.chunks)})
        )
        return doc


if __name__ == "__main__":
    insert_document_example()
