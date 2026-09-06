"""Local sentence-transformer embeddings behind the shared provider boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Callable, Sequence

from app.retrieval.embeddings import EmbeddingProvider, validate_embeddings, validate_texts

# This multilingual sibling retains the 384-dimensional database contract while
# placing Korean and English text in one embedding space.
MULTILINGUAL_SBERT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


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
        self._encoder: Callable[[list[str]], list[list[float]]] | None = None

    def _load(self) -> Callable[[list[str]], list[list[float]]]:
        """Import the model once and wrap it in a plain encode callable.

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

        model = SentenceTransformer(self.model)
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

        self._encoder = encode
        return encode

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode a batch off the event loop and validate before returning."""
        inputs = validate_texts(texts)
        if not inputs:
            return []

        encode = self._load()
        vectors = await asyncio.to_thread(encode, inputs)
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )
