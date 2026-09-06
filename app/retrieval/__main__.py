"""Command-line acceptance path for baseline hybrid retrieval."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
import json
import math
from typing import get_args

from app.config import BM25Idf, EmbeddingProviderName, LexicalRanker, Settings, get_settings
from app.db.bootstrap import bootstrap_schema
from app.ingestion.progress import OperationProgress, OperationProgressCallback, operation_bar
from app.retrieval.bm25 import TermStatCounts, backfill_term_stats
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    OpenAIEmbeddingProvider,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.service import RetrievalResult, retrieve


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and validate retrieval command arguments.

    Parameters
    ----------
    argv : Sequence[str] | None
        Explicit argument sequence, or ``None`` to read process arguments.

    Returns
    -------
    argparse.Namespace
        Validated provider, ranker, preparation, and result-size options.

    Raises
    ------
    SystemExit
        If parsing fails or numeric options violate their contracts.
    """
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
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Rescore fused candidates with a local cross-encoder.",
    )
    parser.add_argument(
        "--lexical-ranker",
        choices=get_args(LexicalRanker),
        help="Override the configured lexical ranker.",
    )
    parser.add_argument(
        "--route-by-language",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override whether a Korean query skips the English lexical component.",
    )
    parser.add_argument("--bm25-k1", type=float, help="Override positive BM25 saturation.")
    parser.add_argument("--bm25-b", type=float, help="Override BM25 length normalization.")
    parser.add_argument(
        "--bm25-idf",
        choices=get_args(BM25Idf),
        help="Override the BM25 inverse-document-frequency variant.",
    )
    parser.add_argument(
        "--rebuild-bm25-stats",
        action="store_true",
        help="Create missing schema objects and atomically rebuild BM25 statistics.",
    )
    args = parser.parse_args(argv)
    if args.k <= 0:
        parser.error("--k must be positive")
    if args.candidate_k is not None and args.candidate_k < args.k:
        parser.error("--candidate-k must be at least --k")
    if args.bm25_k1 is not None and (not math.isfinite(args.bm25_k1) or args.bm25_k1 <= 0):
        parser.error("--bm25-k1 must be a finite positive number")
    if args.bm25_b is not None and (not math.isfinite(args.bm25_b) or not 0 <= args.bm25_b <= 1):
        parser.error("--bm25-b must be a finite number between 0 and 1")
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
    lexical_ranker: LexicalRanker = "ts_rank_cd",
    route_by_language: bool = False,
    bm25_stats: TermStatCounts | None = None,
    embedding_usage: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build JSON output without exposing component-native scores.

    Optional preparation results remain separate from final evidence and rankings.
    """
    return {
        "query": query,
        "provider": provider,
        "backfill": asdict(backfill) if backfill is not None else None,
        "embedding_usage": embedding_usage,
        "lexical_ranker": lexical_ranker,
        "route_by_language": route_by_language,
        "bm25_stats": asdict(bm25_stats) if bm25_stats is not None else None,
        "score_stage": result.score_stage,
        "hits": [hit.model_dump(mode="json") for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


async def _run(
    args: argparse.Namespace,
    *,
    on_progress: OperationProgressCallback | None = None,
) -> dict[str, object]:
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
    lexical_ranker = args.lexical_ranker or settings.lexical_ranker
    routing_override = args.route_by_language
    route_by_language = (
        settings.query_language_routing if routing_override is None else routing_override
    )
    bm25_k1 = settings.bm25_k1 if args.bm25_k1 is None else args.bm25_k1
    bm25_b = settings.bm25_b if args.bm25_b is None else args.bm25_b
    bm25_idf = args.bm25_idf or settings.bm25_idf
    from app.db.session import Session, engine

    try:
        if args.rebuild_bm25_stats:
            if on_progress is not None:
                on_progress(OperationProgress("schema", 0, 1, "Checking schema"))
            await bootstrap_schema(engine)
            if on_progress is not None:
                on_progress(OperationProgress("schema", 1, 1, "Schema ready"))
        async with Session() as session:
            backfill = None
            bm25_stats = None
            if args.rebuild_bm25_stats:
                if on_progress is not None:
                    on_progress(OperationProgress("bm25", 0, 1, "Rebuilding term statistics"))
                bm25_stats = await backfill_term_stats(session)
                if on_progress is not None:
                    on_progress(OperationProgress("bm25", 1, 1, "Term statistics rebuilt"))
            if args.embed_missing:

                def publish_batch(result: EmbeddingBackfillResult) -> None:
                    """Publish cumulative embedding batch progress."""
                    if on_progress is not None:
                        on_progress(
                            OperationProgress(
                                "embedding",
                                result.batches,
                                None,
                                f"{result.embedded} chunks stored",
                            )
                        )

                backfill = await embed_missing_chunks(session, provider, on_batch=publish_batch)
                if on_progress is not None:
                    on_progress(
                        OperationProgress(
                            "embedding",
                            backfill.batches,
                            backfill.batches,
                            f"{backfill.embedded} chunks stored",
                        )
                    )
            result = await retrieve(
                session,
                args.query,
                provider=provider,
                k=args.k,
                candidate_k=args.candidate_k,
                reranker=CrossEncoderReranker() if args.rerank else None,
                route_by_language=route_by_language,
                lexical_ranker=lexical_ranker,
                bm25_k1=bm25_k1,
                bm25_b=bm25_b,
                bm25_idf=bm25_idf,
            )
        return _payload(
            query=args.query,
            provider=settings.embedding_provider,
            backfill=backfill,
            result=result,
            lexical_ranker=lexical_ranker,
            route_by_language=route_by_language,
            bm25_stats=bm25_stats,
            embedding_usage=(
                {
                    "requests": provider.usage.requests,
                    "input_tokens": provider.usage.input_tokens,
                    "estimated_cost_usd": format(provider.usage.estimated_cost_usd, "f"),
                }
                if isinstance(provider, OpenAIEmbeddingProvider)
                else None
            ),
        )
    finally:
        await engine.dispose()


def main() -> None:
    """Run the acceptance command and print machine-readable evidence."""
    with operation_bar("Retrieval preparation") as progress:
        result = asyncio.run(_run(arguments(), on_progress=progress))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
