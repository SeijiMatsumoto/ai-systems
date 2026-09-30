"""Explicit synthetic-corpus ingestion; --provider openai makes live embedding calls."""

import argparse
from pathlib import Path

from backend.internal_knowledge_action.embedding import (
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from backend.internal_knowledge_action.ingestion import (
    INDEX_PATH,
    ingest_fixture,
    load_fixture,
    load_index,
    save_index,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Index the synthetic knowledge fixture"
    )
    parser.add_argument("--provider", choices=("mock", "openai"), required=True)
    parser.add_argument("--index-path", type=Path, default=INDEX_PATH)
    options = parser.parse_args()
    embedder = (
        MockEmbeddingProvider()
        if options.provider == "mock"
        else OpenAIEmbeddingProvider()
    )
    snapshot, report = ingest_fixture(
        load_fixture(), embedder, load_index(options.index_path)
    )
    save_index(snapshot, options.index_path)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
