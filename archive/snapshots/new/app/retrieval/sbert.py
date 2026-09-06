"""Local sentence-transformer embeddings behind the shared provider boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

from app.retrieval.embeddings import EmbeddingProvider, _texts, validate_embeddings

# The multilingual sibling of the default model. It outputs 384 dimensions natively,
# so it drops into ``Settings.sbert_model`` without touching ``embed_dim``, the
# ``Vector(384)`` column, or any migration — the difference is entirely in the space
# the vectors live in, where Korean and English text sit near each other.
MULTILINGUAL_SBERT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class _EmbeddingMatrix(Protocol):
    """Array-like sentence-transformer output used by the provider boundary."""

    def tolist(self) -> list[list[float]]:
        """Return the encoded batch as nested Python floats."""
        ...


class _SentenceEncoder(Protocol):
    """Structural type for the lazily imported sentence-transformer."""

    def get_sentence_embedding_dimension(self) -> int | None:
        """Return the model output width when the model reports one."""
        ...

    def encode(
        self,
        sentences: Sequence[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
    ) -> _EmbeddingMatrix:
        """Encode one batch with the options required by this provider."""
        ...


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Local sentence-transformer embeddings behind the shared provider boundary.

    The model runs inside this process, so after the weights are cached there is no
    API key and no network call. ``sentence_transformers`` is imported lazily, which
    keeps ``app.retrieval`` importable when the project is installed without a torch
    backend extra.

    A local model is not interchangeable with a hosted one. Vectors produced here do
    not share a space with vectors produced by another model, so switching providers
    requires re-embedding every chunk. Mixing them yields no error, only meaningless
    neighbours.
    """

    def __init__(
        self,
        *,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimensions: int = 384,
        batch_size: int = 32,
    ) -> None:
        if not model:
            raise ValueError("embedding model must be nonempty")
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        if batch_size <= 0:
            raise ValueError("embedding batch size must be positive")
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._encoder: _SentenceEncoder | None = None

    def _load(self) -> _SentenceEncoder:
        """Import and construct the encoder once, then reuse it.

        Raises
        ------
        RuntimeError
            If no torch backend extra is installed.
        ValueError
            If the model's output width does not match the database column.
        """
        if self._encoder is not None:
            return self._encoder

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; run one of "
                "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
            ) from exc

        encoder = cast(_SentenceEncoder, SentenceTransformer(self.model))
        reported = encoder.get_sentence_embedding_dimension()
        if reported != self.dimensions:
            raise ValueError(
                f"model {self.model!r} produces {reported} dimensions, "
                f"but this database stores {self.dimensions}"
            )
        self._encoder = encoder
        return encoder

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode a batch off the event loop and validate before returning."""
        inputs = _texts(texts)
        if not inputs:
            return []

        encoder = self._load()

        def _encode() -> list[list[float]]:
            """Run the synchronous, CPU-bound forward pass in a worker thread."""
            return encoder.encode(
                inputs,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).tolist()

        vectors = await asyncio.to_thread(_encode)
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )
