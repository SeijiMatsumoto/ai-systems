from backend.db.schemas import DocumentType
from backend.shared.rag_retrieval import retrieve_document_by_distance


def main() -> None:
    print(
        retrieve_document_by_distance(
            query="What are Apple's most significant business risks?",
            symbol="AAPL",
            document_type=DocumentType.FILING,
            top_n=3,
        )
    )


if __name__ == "__main__":
    main()
