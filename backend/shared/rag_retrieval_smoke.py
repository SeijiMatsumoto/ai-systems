from backend.shared import rag_retrieval

print(
    rag_retrieval.retrieve(
        query="What are Apple's most significant business risks?",
        symbol="AAPL",
        document_type=rag_retrieval.schemas.DocumentType.FILING,
        top_n=3,
    )
)
