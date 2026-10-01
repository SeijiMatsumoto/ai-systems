"""Explicit policy ingestion and bounded hybrid retrieval. Orders are never indexed."""

import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path

from backend.internal_knowledge_action.embedding import (
    STOP_WORDS,
    EmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)

from .contracts import PolicyIndex, PolicySearchArgs, PolicyVector
from .store import MockStore

INDEX_PATH = Path(
    os.getenv(
        "SUPPORT_POLICY_INDEX", "backend/customer_support/.data/policy_index.json"
    )
)
MAX_RESULTS = 3


class IndexUnavailable(ValueError):
    pass


def fingerprint(store: MockStore) -> str:
    payload = {
        "policies": [p.model_dump(mode="json") for p in store.fixture.policies],
        "rules": store.fixture.rules.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def ingest(store: MockStore, embedder: EmbeddingProvider) -> PolicyIndex:
    texts = [p.text for p in store.fixture.policies]
    if not texts or any(not text.strip() or len(text) > 2000 for text in texts):
        raise ValueError("Invalid policy ingestion inputs")
    vectors = embedder.embed_documents(texts)
    if len(vectors) != len(texts):
        raise ValueError("Embedding count mismatch")
    return PolicyIndex(
        fingerprint=fingerprint(store),
        embedding_model=embedder.model_id,
        passages=tuple(
            PolicyVector(
                policy_id=p.policy_id, locator=p.locator, text=p.text, vector=v
            )
            for p, v in zip(store.fixture.policies, vectors)
        ),
    )


def load_index(path: Path = INDEX_PATH) -> PolicyIndex:
    try:
        return PolicyIndex.model_validate_json(path.read_text())
    except (OSError, ValueError) as exc:
        raise IndexUnavailable(
            "Policy index missing or invalid; run explicit policy ingestion"
        ) from exc


def validate_index(
    store: MockStore, index: PolicyIndex, embedder: EmbeddingProvider
) -> None:
    expected = {(p.policy_id, p.locator): p.text for p in store.fixture.policies}
    actual = {(p.policy_id, p.locator): p.text for p in index.passages}
    if (
        index.fingerprint != fingerprint(store)
        or index.embedding_model != embedder.model_id
        or expected != actual
    ):
        raise IndexUnavailable(
            "Policy index does not match fixture or embedding provider; re-ingest explicitly"
        )


def terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in STOP_WORDS
    ]


def search(
    store: MockStore, index: PolicyIndex, embedder: EmbeddingProvider, query: str
) -> tuple[list[PolicyVector], dict]:
    query = PolicySearchArgs(query=query).query
    if not terms(query):
        raise ValueError("Policy query needs searchable text")
    validate_index(store, index, embedder)
    # Bounds and index scope are checked before the embedding provider is invoked.
    vector = embedder.embed_query(query)
    if len(vector) != len(index.passages[0].vector) or any(
        not math.isfinite(x) for x in vector
    ):
        raise ValueError("Query embedding dimensions or values invalid")
    tokenized = [terms(p.text) for p in index.passages]
    df = Counter(t for ts in tokenized for t in set(ts))
    average = sum(len(ts) for ts in tokenized) / len(tokenized)
    lexical, semantic = [], []
    query_terms = set(terms(query))
    for passage, tokens in zip(index.passages, tokenized):
        counts = Counter(tokens)
        score = sum(
            math.log(1 + (len(tokenized) - df[t] + 0.5) / (df[t] + 0.5))
            * counts[t]
            * 2.2
            / (counts[t] + 1.2 * (0.25 + 0.75 * len(tokens) / max(average, 1)))
            for t in query_terms & counts.keys()
        )
        if score > 0:
            lexical.append((f"{passage.policy_id}:{passage.locator}", score))
        norm = math.sqrt(
            sum(x * x for x in vector) * sum(x * x for x in passage.vector)
        )
        cosine = (
            sum(a * b for a, b in zip(vector, passage.vector)) / norm if norm else 0.0
        )
        if cosine > 0:
            semantic.append((f"{passage.policy_id}:{passage.locator}", cosine))
    lexical.sort(key=lambda x: (-x[1], x[0]))
    semantic.sort(key=lambda x: (-x[1], x[0]))
    ranks = {}
    for ranking in (lexical[:8], semantic[:8]):
        for rank, (key, _) in enumerate(ranking, 1):
            ranks[key] = ranks.get(key, 0) + 1 / (60 + rank)
    by_id = {f"{p.policy_id}:{p.locator}": p for p in index.passages}
    # Deterministic bounded rerank rewards phrase and query-term overlap.
    selected = sorted(
        ranks,
        key=lambda key: (
            -(
                ranks[key]
                + 0.01
                * len(query_terms & set(terms(by_id[key].text)))
                / max(len(query_terms), 1)
                + (0.01 if query.lower() in by_id[key].text.lower() else 0)
            ),
            key,
        ),
    )[:MAX_RESULTS]
    return [by_id[key] for key in selected], {
        "lexical": lexical[:8],
        "semantic": semantic[:8],
        "selected": selected,
        "embedding_model": index.embedding_model,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Explicitly index synthetic retailer policies"
    )
    parser.add_argument("--provider", choices=("mock", "openai"), required=True)
    parser.add_argument("--index-path", type=Path, default=INDEX_PATH)
    args = parser.parse_args()
    embedder = (
        MockEmbeddingProvider()
        if args.provider == "mock"
        else OpenAIEmbeddingProvider()
    )
    index = ingest(MockStore.load(), embedder)
    args.index_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.index_path.with_suffix(".tmp")
    temporary.write_text(index.model_dump_json(indent=2))
    temporary.replace(args.index_path)
    print(
        json.dumps(
            {
                "passages": len(index.passages),
                "embedding_model": index.embedding_model,
                "path": str(args.index_path),
            }
        )
    )


if __name__ == "__main__":
    main()
