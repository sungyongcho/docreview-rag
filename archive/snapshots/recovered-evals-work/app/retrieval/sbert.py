"""Local sentence-transformer embeddings behind the shared provider boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol, cast

from app.retrieval._sentence_transformers import ThreadSafeLazy, sentence_transformers_attribute
from app.retrieval.embeddings import EmbeddingProvider, validate_embeddings, validate_texts


class _EmbeddingMatrix(Protocol):
    """Array-like result returned by sentence-transformers."""

    def tolist(self) -> list[list[float]]:
        """Convert the model output to plain Python lists."""
        ...


class _SentenceTransformer(Protocol):
    """Synchronous subset of the optional embedding dependency."""

    def get_sentence_embedding_dimension(self) -> int | None:
        """Return the configured model's embedding width."""
        ...

    def encode(
        self,
        inputs: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
    ) -> _EmbeddingMatrix:
        """Encode one batch into a matrix."""
        ...


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Local sentence-transformer embeddings behind the shared provider boundary.

    Model construction is lazy and thread-safe. Switching models requires re-embedding
    every chunk because vector spaces are not interchangeable.
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
        self._encoder = ThreadSafeLazy[Callable[[list[str]], list[list[float]]]]()

    def _load(self) -> Callable[[list[str]], list[list[float]]]:
        """Return the cached encoder, constructing it once when absent.

        Returns
        -------
        Callable[[list[str]], list[list[float]]]
            Validated synchronous batch encoder.

        Raises
        ------
        RuntimeError
            If no torch backend extra is installed.
        ValueError
            If the model's output width does not match the database column.
        """
        return self._encoder.get(self._build_encoder)

    def _build_encoder(self) -> Callable[[list[str]], list[list[float]]]:
        """Construct an encoder whose width matches the database contract."""
        sentence_transformer = cast(
            Callable[[str], _SentenceTransformer],
            sentence_transformers_attribute("SentenceTransformer"),
        )
        model = sentence_transformer(self.model)
        reported = model.get_sentence_embedding_dimension()
        if reported != self.dimensions:
            raise ValueError(
                f"model {self.model!r} produces {reported} dimensions, "
                f"but this database stores {self.dimensions}"
            )

        def encode(inputs: list[str]) -> list[list[float]]:
            """Run the synchronous, CPU-bound forward pass for one batch."""
            return model.encode(
                inputs,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).tolist()

        return encode

    def _encode(self, inputs: list[str]) -> list[list[float]]:
        """Load the model if needed and run inference in the current worker."""
        return self._load()(inputs)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode and validate one batch without blocking the event loop.

        Parameters
        ----------
        texts : Sequence[str]
            Nonempty source texts in caller order.

        Returns
        -------
        list[list[float]]
            Finite vectors in caller order and database dimensions.

        Raises
        ------
        RuntimeError
            If the optional sentence-transformer dependency is unavailable.
        ValueError
            If input or model output violates the embedding contract.
        """
        inputs = validate_texts(texts)
        if not inputs:
            return []

        vectors = await asyncio.to_thread(self._encode, inputs)
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )
