"""Local cross-encoder provider behind the optional reranking boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol, cast

from app.retrieval._sentence_transformers import ThreadSafeLazy, sentence_transformers_attribute
from app.retrieval.rerank import RerankProvider


class _CrossEncoder(Protocol):
    """Synchronous subset of the optional cross-encoder dependency."""

    def predict(
        self,
        pairs: list[tuple[str, str]],
        *,
        batch_size: int,
    ) -> Sequence[float]:
        """Return one relevance score per query/document pair."""
        ...


class CrossEncoderReranker(RerankProvider):
    """Rerank with a cross-encoder that reads the query and document together.

    Model construction is lazy and thread-safe. Raw logits are meaningful only for
    ordering the supplied candidate set, not as probabilities or cross-strategy scores.
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
        self._encoder = ThreadSafeLazy[Callable[[list[tuple[str, str]]], list[float]]]()

    def _load(self) -> Callable[[list[tuple[str, str]]], list[float]]:
        """Return the cached predictor, constructing it once when absent.

        Returns
        -------
        Callable[[list[tuple[str, str]]], list[float]]
            Synchronous batch predictor.

        Raises
        ------
        RuntimeError
            If no torch backend extra is installed.
        """
        return self._encoder.get(self._build_encoder)

    def _build_encoder(self) -> Callable[[list[tuple[str, str]]], list[float]]:
        """Construct the provider-specific reranking callable."""
        cross_encoder = cast(
            Callable[[str], _CrossEncoder],
            sentence_transformers_attribute("CrossEncoder"),
        )
        model = cross_encoder(self.model)

        def predict(pairs: list[tuple[str, str]]) -> list[float]:
            """Run the synchronous, CPU-bound forward passes for one batch."""
            return [float(value) for value in model.predict(pairs, batch_size=self.batch_size)]

        return predict

    def _predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Load the model if needed and run inference in the current worker."""
        return self._load()(pairs)

    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Score query/document pairs without blocking the event loop.

        Parameters
        ----------
        query : str
            Query paired with every candidate document.
        documents : Sequence[str]
            Candidate indexed texts in caller order.

        Returns
        -------
        Sequence[float]
            Raw relevance logits in caller order.

        Raises
        ------
        RuntimeError
            If the optional cross-encoder dependency is unavailable.
        """
        pairs = [(query, document) for document in documents]
        if not pairs:
            return []

        return await asyncio.to_thread(self._predict, pairs)
