"""Embedding contracts, validation, and provider selection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import math
import re
import unicodedata

from app.config import Settings, get_settings
from app.retrieval.types import finite_float


def validate_texts(values: Sequence[str]) -> list[str]:
    """Return validated, materialized embedding inputs.

    Parameters
    ----------
    values : Sequence[str]
        Input texts supplied by a caller.

    Returns
    -------
    list[str]
        Materialized list that preserves caller order.

    Raises
    ------
    ValueError
        If any input is empty or is not a string.
    """
    texts = list(values)
    if any(not isinstance(text, str) or not text for text in texts):
        raise ValueError("embedding inputs must be nonempty strings")
    return texts


def validate_embeddings(
    values: Sequence[Sequence[float]], *, expected_count: int, dimensions: int
) -> list[list[float]]:
    """Validate provider output before it crosses the database boundary.

    Parameters
    ----------
    values : Sequence[Sequence[float]]
        Provider vectors in caller order.
    expected_count : int
        Number of vectors requested by the caller.
    dimensions : int
        Required number of components in each vector.

    Returns
    -------
    list[list[float]]
        Finite, nonzero vectors materialized as built-in floats.

    Raises
    ------
    ValueError
        If dimensions, count, shape, numeric type, finiteness, or vector norm is invalid.
    """
    if dimensions <= 0:
        raise ValueError("embedding dimensions must be positive")
    if len(values) != expected_count:
        raise ValueError(
            f"embedding provider returned {len(values)} vectors for {expected_count} inputs"
        )

    vectors: list[list[float]] = []
    for position, value in enumerate(values):
        if len(value) != dimensions:
            raise ValueError(
                f"embedding {position} has dimension {len(value)}, expected {dimensions}"
            )
        nonnumeric = f"embedding {position} contains a nonnumeric component"
        nonfinite = f"embedding {position} contains a non-finite component"
        vector = [
            finite_float(component, nonnumeric=nonnumeric, nonfinite=nonfinite)
            for component in value
        ]
        if not any(vector):
            raise ValueError(f"embedding {position} must have a nonzero norm")
        vectors.append(vector)
    return vectors


@dataclass(frozen=True, slots=True)
class EmbeddingIdentity:
    """Provider, model, and dimensions defining one vector space."""

    provider: str
    model: str
    dimensions: int
    tokenizer: str

    def __post_init__(self) -> None:
        """Reject incomplete identities before querying or persisting vector spaces."""
        if not self.provider.strip() or not self.model.strip() or not self.tokenizer.strip():
            raise ValueError("embedding configuration fields must be nonblank")
        if self.dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")


class EmbeddingProvider(ABC):
    """Async provider boundary shared by query and document embeddings."""

    dimensions: int

    @property
    @abstractmethod
    def max_input_tokens(self) -> int:
        """Declare the model's maximum complete input, including special tokens."""

    @abstractmethod
    def count_input_tokens(self, text: str) -> int:
        """Count complete model input without truncating it."""

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch in caller order."""

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query through the same model and validation path."""
        return (await self.embed_documents([text]))[0]

    @property
    @abstractmethod
    def identity(self) -> EmbeddingIdentity:
        """Declare the complete provider, model, dimension, and tokenizer configuration."""


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Stable token-hashing vectors for tests and local exercises."""

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self.dimensions = dimensions

    @property
    def max_input_tokens(self) -> int:
        """Apply the shared hard ceiling to the explicit deterministic tokenizer."""
        return 8192

    def count_input_tokens(self, text: str) -> int:
        """Count the exact normalized Unicode words used by deterministic embedding."""
        validate_texts([text])
        return max(1, len(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())))

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Hash normalized alphanumeric tokens into unit-length bag-of-words vectors."""
        inputs = validate_texts(texts)
        if any(self.count_input_tokens(text) > self.max_input_tokens for text in inputs):
            raise ValueError("deterministic input exceeds its 8192-token limit")
        vectors: list[list[float]] = []
        for text in inputs:
            normalized = unicodedata.normalize("NFKC", text).casefold()
            tokens = re.findall(r"[^\W_]+", normalized)
            if not tokens:
                tokens = ["<empty>"]
            vector = [0.0] * self.dimensions
            for token in tokens:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                dimension = int.from_bytes(digest[:8], "big") % self.dimensions
                sign = 1.0 if digest[8] & 1 else -1.0
                vector[dimension] += sign
            norm = math.sqrt(sum(component * component for component in vector))
            if norm == 0.0:
                digest = hashlib.sha256(" ".join(tokens).encode("utf-8")).digest()
                vector[int.from_bytes(digest[:8], "big") % self.dimensions] = 1.0
                norm = 1.0
            vectors.append([component / norm for component in vector])
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )

    @property
    def identity(self) -> EmbeddingIdentity:
        """Return the deterministic token-hash identity."""
        return EmbeddingIdentity(
            "deterministic",
            f"token-hash-{self.dimensions}",
            self.dimensions,
            "unicode-alnum:nfkc:casefold:v1",
        )


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Build the configured provider without work at module import time.

    Parameters
    ----------
    settings : Settings | None
        Validated settings, or ``None`` to load cached application settings.

    Returns
    -------
    EmbeddingProvider
        Deterministic or OpenAI provider selected by configuration.
    """
    configured = settings or get_settings()
    if configured.embedding_provider == "deterministic":
        return DeterministicEmbeddingProvider(configured.embed_dim)
    if configured.embedding_provider == "sbert":
        from app.retrieval.embedding.sbert import SentenceTransformerEmbeddingProvider

        return SentenceTransformerEmbeddingProvider(
            model=configured.sbert_model,
            dimensions=configured.embed_dim,
        )
    api_key = configured.openai_api_key.get_secret_value() if configured.openai_api_key else None
    from app.retrieval.embedding.openai import OpenAIEmbeddingProvider

    return OpenAIEmbeddingProvider(
        model=configured.embedding_model,
        dimensions=configured.embed_dim,
        api_key=api_key,
        credential_slot=configured.openai_key_slot,
    )
