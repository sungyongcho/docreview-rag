"""Command-line acceptance path for baseline hybrid retrieval."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
import json
from typing import get_args

from app.config import EmbeddingProviderName, Settings, get_settings
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.service import RetrievalResult, retrieve


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse baseline retrieval arguments."""
    parser = argparse.ArgumentParser(description="Run exact hybrid retrieval over PostgreSQL.")
    parser.add_argument("--query", required=True, help="Nonempty retrieval query.")
    parser.add_argument("--k", type=int, default=5, help="Number of fused hits to return.")
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Candidates per component; defaults to max(20, 4 * k).",
    )
    parser.add_argument(
        "--provider",
        choices=get_args(EmbeddingProviderName),
        help="Override the configured embedding provider for this command.",
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    args = parser.parse_args(argv)
    if args.k <= 0:
        parser.error("--k must be positive")
    if args.candidate_k is not None and args.candidate_k < args.k:
        parser.error("--candidate-k must be at least --k")
    return args


def _provider_settings(settings: Settings, provider: EmbeddingProviderName | None) -> Settings:
    """Return settings with an optional validated provider override."""
    if provider is None:
        return settings
    return Settings.model_validate(settings.model_dump() | {"embedding_provider": provider})


def _payload(
    *,
    query: str,
    provider: str,
    backfill: EmbeddingBackfillResult | None,
    result: RetrievalResult,
) -> dict[str, object]:
    """Build JSON output without exposing component-native scores."""
    return {
        "query": query,
        "provider": provider,
        "backfill": asdict(backfill) if backfill is not None else None,
        "score_stage": result.score_stage,
        "hits": [hit.model_dump(mode="json") for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    """Run optional embedding backfill and one retrieval request.

    Parameters
    ----------
    args : argparse.Namespace
        Validated provider, query, and result-size arguments.

    Returns
    -------
    dict[str, object]
        JSON-serializable retrieval evidence and optional backfill counters.
    """
    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    from app.db.session import Session, engine

    try:
        async with Session() as session:
            backfill = None
            if args.embed_missing:
                backfill = await embed_missing_chunks(session, provider)
            result = await retrieve(
                session,
                args.query,
                provider=provider,
                k=args.k,
                candidate_k=args.candidate_k,
            )
        return _payload(
            query=args.query,
            provider=settings.embedding_provider,
            backfill=backfill,
            result=result,
        )
    finally:
        await engine.dispose()


def main() -> None:
    """Run the acceptance command and print machine-readable evidence."""
    print(json.dumps(asyncio.run(_run(arguments())), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
