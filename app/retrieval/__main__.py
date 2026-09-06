"""Command-line acceptance path for the M2 retrieval service."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
import json
from typing import get_args

from app.config import BM25Idf, EmbeddingProviderName, LexicalRanker, Settings, get_settings
from app.db.bootstrap import bootstrap_schema
from app.db.session import Session, engine
from app.retrieval.bm25 import TermStatCounts, backfill_term_stats
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.service import RetrievalResult, retrieve


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse retrieval acceptance arguments."""
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
        help=(
            "Override EMBEDDING_PROVIDER for this command. Stored embeddings are only "
            "comparable with query embeddings from the same provider, so switching "
            "requires re-embedding every chunk with --embed-missing on an empty column."
        ),
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Rescore fused candidates with a local cross-encoder before truncating to k.",
    )
    parser.add_argument(
        "--lexical-ranker",
        choices=get_args(LexicalRanker),
        help="Override LEXICAL_RANKER for this command.",
    )
    parser.add_argument(
        "--bm25-k1",
        type=float,
        help="Override BM25_K1; must be positive.",
    )
    parser.add_argument(
        "--bm25-b",
        type=float,
        help="Override BM25_B; must be between 0 and 1.",
    )
    parser.add_argument(
        "--bm25-idf",
        choices=get_args(BM25Idf),
        help="Override BM25_IDF; 'robertson' can score common terms negatively.",
    )
    parser.add_argument(
        "--rebuild-bm25-stats",
        action="store_true",
        help="Create missing schema objects and atomically rebuild BM25 term statistics.",
    )
    return parser.parse_args(argv)


def _provider_settings(settings: Settings, provider: EmbeddingProviderName | None) -> Settings:
    """Return settings with an optional validated command-line provider override."""
    if provider is None:
        return settings
    return settings.model_copy(update={"embedding_provider": provider})


def _payload(
    *,
    query: str,
    provider: str,
    backfill: EmbeddingBackfillResult | None,
    result: RetrievalResult,
    lexical_ranker: LexicalRanker = "ts_rank_cd",
    bm25_k1: float = 1.2,
    bm25_b: float = 0.75,
    bm25_idf: BM25Idf = "lucene",
    bm25_stats: TermStatCounts | None = None,
) -> dict[str, object]:
    """Build stable JSON output while keeping component scores private."""
    return {
        "query": query,
        "provider": provider,
        "lexical_ranker": lexical_ranker,
        "bm25_k1": bm25_k1 if lexical_ranker == "bm25" else None,
        "bm25_b": bm25_b if lexical_ranker == "bm25" else None,
        "bm25_idf": bm25_idf if lexical_ranker == "bm25" else None,
        "bm25_stats": asdict(bm25_stats) if bm25_stats is not None else None,
        "backfill": asdict(backfill) if backfill is not None else None,
        "hits": [hit.model_dump(mode="json") for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    """Run optional preparation work and one configured retrieval request.

    Parameters
    ----------
    args : argparse.Namespace
        Validated CLI arguments controlling providers, backfills, rankers, and result size.

    Returns
    -------
    dict[str, object]
        JSON-serializable retrieval evidence and preparation counters.

    Notes
    -----
    The cross-encoder is constructed only when reranking is requested, and its model
    weights remain lazily loaded until the service has candidates to rescore.
    """
    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    lexical_ranker = args.lexical_ranker or settings.lexical_ranker
    bm25_k1 = settings.bm25_k1 if args.bm25_k1 is None else args.bm25_k1
    bm25_b = settings.bm25_b if args.bm25_b is None else args.bm25_b
    bm25_idf = args.bm25_idf or settings.bm25_idf
    if args.rebuild_bm25_stats:
        await bootstrap_schema(engine)
    async with Session() as session:
        backfill = None
        bm25_stats = None
        if args.rebuild_bm25_stats:
            bm25_stats = await backfill_term_stats(session)
        if args.embed_missing:
            backfill = await embed_missing_chunks(session, provider)
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            reranker=CrossEncoderReranker() if args.rerank else None,
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
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
        bm25_idf=bm25_idf,
        bm25_stats=bm25_stats,
    )


def main() -> None:
    """Run the M2 acceptance command and print machine-readable evidence."""
    print(json.dumps(asyncio.run(_run(arguments())), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
