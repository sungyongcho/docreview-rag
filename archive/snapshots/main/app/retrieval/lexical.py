import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.retrieval.types import ChunkHit


async def lexical_search(
    session: AsyncSession, query: str, k: int = 20
) -> list[ChunkHit]:
    def _or_tsquery(query: str):
        words = re.findall(r"\w+", query)
        if not words:
            return None
        tsq = func.plainto_tsquery("english", words[0])
        for w in words[1:]:
            tsq = tsq.op("||")(func.plainto_tsquery("english", w))
        return tsq

    # tsq = func.plainto_tsquery("english", query)
    tsq = _or_tsquery(query)
    if tsq is None:
        return []
    rank = func.ts_rank(Chunk.content_tsv, tsq)
    stmt = (
        select(Chunk, rank.label("rank"))
        .where(Chunk.content_tsv.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(k)
    )

    rows = (await session.execute(stmt)).all()
    return [
        ChunkHit(
            doc_id=c.doc_id,
            section=c.section,
            snippet=(c.content or c.heading)[:200],
            score=float(r),
            citation=c.citation,
        )
        for c, r in rows
    ]


if __name__ == "__main__":
    import argparse
    import asyncio

    from app.db.session import Session

    async def main():
        p = argparse.ArgumentParser()
        p.add_argument("--query", required=True)
        p.add_argument("-k", type=int, default=10)
        a = p.parse_args()
        async with Session() as session:
            for h in await lexical_search(session, a.query, k=a.k):
                print(f"  {h.citation:12} rank={h.score:.4f} | {h.snippet[:50]}")

    asyncio.run(main())
