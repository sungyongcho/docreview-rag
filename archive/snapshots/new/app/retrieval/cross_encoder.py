"""Cross-encoder reranking provider for the M2.6 boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

from app.retrieval.rerank import RerankProvider


class _CrossEncoderModel(Protocol):
    """Structural type for the lazily imported cross-encoder."""

    def predict(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
    ) -> Sequence[float]:
        """Score query/document pairs in caller order."""
        ...


class CrossEncoderReranker(RerankProvider):
    """Rerank with a cross-encoder that reads the query and document together.

    The vector path in M2.3 is a bi-encoder: it embeds the query and the chunk
    separately and compares the two vectors afterwards, so the two texts never meet
    inside the model. That separation is what makes it cheap enough to run over the
    whole corpus, and also what limits its accuracy.

    A cross-encoder concatenates the query and one document into a single input and
    returns one relevance score. It reads both together, which is more accurate and
    costs one forward pass per candidate. That price is only affordable on a short
    list, which is why reranking runs after fusion rather than instead of it.

    The returned scores are raw logits. They are not probabilities, they are not
    bounded, and they are not comparable with cosine similarity or with BM25.
    """

    def __init__(
        self,
        *,
        model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        batch_size: int = 32,
    ) -> None:
        if not model:
            raise ValueError("reranker model must be nonempty")
        if batch_size <= 0:
            raise ValueError("reranker batch size must be positive")
        self.model = model
        self.batch_size = batch_size
        self._encoder: _CrossEncoderModel | None = None

    def _load(self) -> _CrossEncoderModel:
        """Import and construct the cross-encoder once, then reuse it."""
        if self._encoder is not None:
            return self._encoder

        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; run one of "
                "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
            ) from exc

        self._encoder = cast(_CrossEncoderModel, CrossEncoder(self.model))
        return self._encoder

    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Score every query/document pair off the event loop, in caller order."""
        pairs = [(query, document) for document in documents]
        if not pairs:
            return []

        encoder = self._load()

        def _predict() -> list[float]:
            """Run the synchronous, CPU-bound forward passes in a worker thread."""
            return [float(value) for value in encoder.predict(pairs, batch_size=self.batch_size)]

        return await asyncio.to_thread(_predict)
