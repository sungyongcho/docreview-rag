from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.embeddings import Embedder
from app.retrieval.lexical import lexical_search
from app.retrieval.types import ChunkHit
from app.retrieval.vector import vector_search


def rrf_fuse(rankings: list[list[ChunkHit]], k_const: int = 60) -> list[ChunkHit]:
    # 문서 점수 = Σ (검색기별) 1 / (k_const + rank)
    # # rank는 그 검색기 결과에서의 순위(1부터), k_const=60
    scores: dict[str, float] = {}
    hit_by_key: dict[str, ChunkHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            key = hit.citation
            scores[key] = scores.get(key, 0.0) + 1.0 / (k_const + rank)
            hit_by_key.setdefault(key, hit)
    fused = [
        ChunkHit(
            doc_id=h.doc_id,
            section=h.section,
            snippet=h.snippet,
            score=scores[key],
            citation=h.citation,
        )
        for key, h in hit_by_key.items()
    ]
    fused.sort(key=lambda x: x.score, reverse=True)
    return fused


async def hybrid_search(
    session: AsyncSession,
    query: str,
    embedder: Embedder,
    k: int = 5,
    candidates: int = 20,
) -> list[ChunkHit]:
    vec_hits = await vector_search(session, embedder.embed_query(query), k=candidates)
    lex_hits = await lexical_search(session, query, k=candidates)
    fused = rrf_fuse([vec_hits, lex_hits], k_const=60)
    return fused[:k]


if __name__ == "__main__":
    import argparse
    import asyncio

    from app.config import get_settings
    from app.db.session import Session
    from app.retrieval.embeddings import get_embedder

    async def main():
        p = argparse.ArgumentParser()
        p.add_argument("--query", required=True)
        p.add_argument("-k", type=int, default=5)
        a = p.parse_args()
        embedder = get_embedder(get_settings())
        async with Session() as session:
            for h in await hybrid_search(session, a.query, embedder, k=a.k):
                print(f"  {h.citation:12} rrf={h.score:.4f} | {h.snippet[:50]}")

    asyncio.run(main())
