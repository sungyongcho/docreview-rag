"""Transactional rebuilding of corpus BM25 term statistics."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BM25CorpusStat, ChunkLength, ChunkTerm, LexemeStat


@dataclass(frozen=True, slots=True)
class TermStatCounts:
    """Committed row counts for one complete BM25 statistic rebuild."""

    terms: int
    chunks: int
    lexemes: int


async def backfill_term_stats(session: AsyncSession) -> TermStatCounts:
    """Atomically rebuild every BM25 statistic from ``chunks.content_tsv``.

    Parameters
    ----------
    session : AsyncSession
        Idle session that owns the rebuild transaction.

    Returns
    -------
    TermStatCounts
        Committed term, chunk-length, and lexeme row counts.

    Raises
    ------
    RuntimeError
        If the session already owns an active transaction.

    Notes
    -----
    Source and derived-table locks keep the rebuilt rows and the per-language corpus
    rows (document count and average length for each corpus language) on one
    consistent chunk snapshot.
    """
    if session.in_transaction():
        raise RuntimeError("backfill_term_stats requires a session without an active transaction")

    async with session.begin():
        await session.execute(text("LOCK TABLE chunks IN SHARE MODE"))
        await session.execute(
            text(
                "LOCK TABLE chunk_terms, chunk_lengths, lexeme_stats, bm25_corpus_stats "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )
        await session.execute(delete(BM25CorpusStat))
        await session.execute(delete(ChunkTerm))
        await session.execute(delete(ChunkLength))
        await session.execute(delete(LexemeStat))

        await session.execute(
            text(
                "INSERT INTO chunk_terms (chunk_id, lexeme, tf) "
                "SELECT c.id, t.lexeme, cardinality(t.positions) "
                "FROM chunks AS c CROSS JOIN LATERAL unnest(c.content_tsv) AS t "
                "WHERE t.positions IS NOT NULL AND cardinality(t.positions) > 0"
            )
        )
        await session.execute(
            text(
                "INSERT INTO chunk_lengths (chunk_id, dl) "
                "SELECT chunk_id, SUM(tf) FROM chunk_terms GROUP BY chunk_id"
            )
        )
        # Both derived statistics are partitioned by the chunk's corpus language:
        # the corpora share one table but are tokenized differently, so a global
        # N/avgdl/df would score each corpus against the other's distribution.
        await session.execute(
            text(
                "INSERT INTO lexeme_stats (language, lexeme, df) "
                "SELECT c.language, ct.lexeme, COUNT(*) "
                "FROM chunk_terms AS ct JOIN chunks AS c ON c.id = ct.chunk_id "
                "GROUP BY c.language, ct.lexeme"
            )
        )
        await session.execute(
            text(
                "INSERT INTO bm25_corpus_stats (language, n, avgdl) "
                "SELECT c.language, COUNT(*), AVG(cl.dl)::double precision "
                "FROM chunk_lengths AS cl JOIN chunks AS c ON c.id = cl.chunk_id "
                "GROUP BY c.language"
            )
        )

        row = (
            await session.execute(
                select(
                    select(func.count()).select_from(ChunkTerm).scalar_subquery().label("terms"),
                    select(func.count()).select_from(ChunkLength).scalar_subquery().label("chunks"),
                    select(func.count()).select_from(LexemeStat).scalar_subquery().label("lexemes"),
                )
            )
        ).one()
        counts = TermStatCounts(
            terms=int(row.terms),
            chunks=int(row.chunks),
            lexemes=int(row.lexemes),
        )

    return counts
