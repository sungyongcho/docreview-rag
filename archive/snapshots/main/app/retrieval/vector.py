from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.retrieval.types import ChunkHit


async def vector_search(
    session: AsyncSession, query_emb: list[float], k: int = 5
) -> list[ChunkHit]:
    distance = Chunk.embedding.cosine_distance(query_emb)
    stmt = select(Chunk, distance.label("distance")).order_by(distance).limit(k)
    rows = (await session.execute(stmt)).all()
    return [
        ChunkHit(
            doc_id=chunk.doc_id,
            section=chunk.section,
            snippet=(chunk.content or chunk.heading)[:200],
            score=1.0 - dist,
            citation=chunk.citation,
        )
        for chunk, dist in rows
    ]


if __name__ == "__main__":
    import argparse
    import asyncio

    from app.config import get_settings
    from app.db.session import Session
    from app.retrieval.embeddings import get_embedder

    async def main() -> None:
        p = argparse.ArgumentParser()
        p.add_argument("--query", required=True)
        p.add_argument("-k", type=int, default=5)
        a = p.parse_args()

        settings = get_settings()
        q_emb = get_embedder(settings).embed_query(a.query)
        async with Session() as session:
            for hit in await vector_search(session, q_emb, k=a.k):
                print(f"  {hit.citation:12} score={hit.score:.3f} | {hit.snippet[:50]}")

    asyncio.run(main())
