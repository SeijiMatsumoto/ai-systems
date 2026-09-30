"""Embedding boundary: a real adapter and an explicit offline test double."""

import hashlib
import math
import re
from collections import Counter
from pathlib import Path
from typing import ClassVar, Protocol

from dotenv import load_dotenv
from openai import OpenAI

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "can",
        "do",
        "for",
        "how",
        "i",
        "in",
        "is",
        "me",
        "my",
        "of",
        "on",
        "the",
        "to",
        "what",
        "where",
        "with",
    }
)


class EmbeddingProvider(Protocol):
    model_id: str

    def embed_documents(self, texts: list[str]) -> list[tuple[float, ...]]: ...

    def embed_query(self, text: str) -> tuple[float, ...]: ...


class OpenAIEmbeddingProvider:
    """Live adapter, called only by explicitly selected ingestion/query paths."""

    model_id = "text-embedding-3-small"

    def __init__(self, client: OpenAI | None = None) -> None:
        if client is None:
            load_dotenv(Path(__file__).parents[1] / ".env", override=False)
        self.client = client or OpenAI(timeout=20.0, max_retries=1)

    def embed_documents(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        response = self.client.embeddings.create(model=self.model_id, input=texts)
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise ValueError("Embedding provider returned the wrong number of vectors")
        if [item.index for item in ordered] != list(range(len(texts))):
            raise ValueError("Embedding provider returned unexpected vector indexes")
        return [tuple(item.embedding) for item in ordered]

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self.embed_documents([text])[0]


class MockEmbeddingProvider:
    """Deterministic vectors for offline architecture checks, not semantic quality claims."""

    model_id = "mock-embedding-v1"
    dimensions = 128
    _aliases: ClassVar[dict[str, str]] = {
        "pto": "leave",
        "vacation": "leave",
        "holiday": "leave",
        "left": "remaining",
        "reimbursement": "refund",
        "oncall": "rotation",
        "deployment": "deploy",
        "deployments": "deploy",
    }

    def _embed(self, text: str) -> tuple[float, ...]:
        text = re.sub(r"\btime off\b", "leave", text.lower())
        terms = Counter(
            self._aliases.get(token, token)
            for token in TOKEN_PATTERN.findall(text)
            if token not in STOP_WORDS
        )
        vector = [0.0] * self.dimensions
        for term, count in terms.items():
            position = (
                int.from_bytes(hashlib.sha256(term.encode()).digest()[:4], "big")
                % self.dimensions
            )
            vector[position] += float(count)
        norm = math.sqrt(sum(value * value for value in vector))
        return tuple(value / norm for value in vector) if norm else tuple(vector)

    def embed_documents(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._embed(text)
