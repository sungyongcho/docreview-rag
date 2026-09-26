"""OpenAI embedding batching and billable response accounting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.ingestion.tokens import MAX_REQUEST_INPUTS, MAX_REQUEST_TOKENS, tokenizer, validate_request
from app.observability.usage import emit_embedding_usage, provider_identity, usage_record
from app.openai_models import resolve_openai_model
from app.release.ai_allowance import reserve_openai
from app.retrieval.embedding.provider import (
    EmbeddingIdentity,
    EmbeddingProvider,
    validate_embeddings,
    validate_texts,
)

if TYPE_CHECKING:
    from openai import AsyncOpenAI


@dataclass(frozen=True, slots=True)
class EmbeddingUsage:
    """Cumulative OpenAI embedding usage and exact estimated cost."""

    requests: int = 0
    input_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider with explicit output dimensions."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-large",
        dimensions: int = 384,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        credential_slot: str | None = None,
    ) -> None:
        selection = resolve_openai_model("embedding", model)
        if dimensions != selection.dimensions:
            raise ValueError(
                f"embedding dimensions must be {selection.dimensions} for {selection.model}"
            )
        self.model = selection.model
        self.dimensions = dimensions
        self._input_price = selection.pricing.input_per_million_usd
        self._usage = EmbeddingUsage()
        self.usage_identity = provider_identity(
            provider="openai_embeddings",
            local=False,
            credential_slot=credential_slot or ("explicit" if api_key else None),
        )
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, max_retries=0)
        self._client = client

    @property
    def max_input_tokens(self) -> int:
        """Return the supported complete-input OpenAI embedding limit."""
        return 8192

    def count_input_tokens(self, text: str) -> int:
        """Count literal source text with the actual embedding model encoding."""
        validate_texts([text])
        return len(tokenizer(self.model).encode(text, disallowed_special=()))

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Preflight all complete inputs, then issue safely bounded provider requests."""
        inputs = validate_texts(texts)
        counts = [validate_request([text], model=self.model)[0] for text in inputs]
        batches: list[list[str]] = []
        current: list[str] = []
        total = 0
        for text, count in zip(inputs, counts, strict=True):
            if current and (
                len(current) == MAX_REQUEST_INPUTS or total + count > MAX_REQUEST_TOKENS
            ):
                batches.append(current)
                current = []
                total = 0
            current.append(text)
            total += count
        if current:
            batches.append(current)
        vectors: list[list[float]] = []
        for batch in batches:
            vectors.extend(await self._embed_request(batch))
        return vectors

    async def _embed_request(self, inputs: list[str]) -> list[list[float]]:
        """Issue one preflighted request and restore its exact input order."""
        tokens = sum(validate_request(inputs, model=self.model))
        await reserve_openai(Decimal(tokens) * self._input_price / Decimal(1_000_000))
        try:
            response = await self._client.embeddings.create(
                input=inputs,
                model=self.model,
                dimensions=self.dimensions,
                encoding_format="float",
            )
        except BaseException:
            await emit_embedding_usage(
                usage_record(identity=self.usage_identity, model_name=self.model, role="embedding")
            )
            raise
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        if type(input_tokens) is not int or input_tokens < 0:
            await emit_embedding_usage(
                usage_record(identity=self.usage_identity, model_name=self.model, role="embedding")
            )
            raise ValueError("OpenAI embedding response did not include token usage")
        cost = Decimal(input_tokens) * self._input_price / Decimal(1_000_000)
        # A returned billable response remains usage even if its vectors fail validation.
        self._usage = EmbeddingUsage(
            requests=self._usage.requests + 1,
            input_tokens=self._usage.input_tokens + input_tokens,
            estimated_cost_usd=self._usage.estimated_cost_usd + cost,
        )
        await emit_embedding_usage(
            usage_record(
                identity=self.usage_identity,
                model_name=self.model,
                role="embedding",
                input_tokens=input_tokens,
                estimated_cost_usd=cost,
            )
        )
        by_index: dict[int, Sequence[float]] = {}
        for item in response.data:
            if not isinstance(item.index, int) or item.index in by_index:
                raise ValueError("embedding provider returned invalid response indices")
            by_index[item.index] = item.embedding
        if set(by_index) != set(range(len(inputs))):
            raise ValueError("embedding provider returned incomplete response indices")
        ordered = [by_index[index] for index in range(len(inputs))]
        vectors = validate_embeddings(
            ordered,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )
        return vectors

    @property
    def usage(self) -> EmbeddingUsage:
        """Return cumulative usage for requests this provider instance issued."""
        return self._usage

    @property
    def identity(self) -> EmbeddingIdentity:
        """Return the configured OpenAI embedding identity."""
        return EmbeddingIdentity(
            "openai",
            self.model,
            self.dimensions,
            f"tiktoken:{tokenizer(self.model).name}:literal-special:v1",
        )
