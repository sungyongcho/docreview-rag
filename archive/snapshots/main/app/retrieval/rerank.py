from dataclasses import replace

from sentence_transformers import CrossEncoder

from app.retrieval.types import ChunkHit


class Reranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = CrossEncoder(model_name)

    def rerank(
        self, query: str, hits: list[ChunkHit], top_k: int = 5
    ) -> list[ChunkHit]:
        if not hits:
            return []
        scores = self.model.predict([(query, h.snippet) for h in hits])
        return self._rerank_by_scores(hits, scores, top_k)

    @staticmethod
    def _rerank_by_scores(hits: list[ChunkHit], scores, top_k: int) -> list[ChunkHit]:
        reordered = sorted(zip(hits, scores), key=lambda x: x[1], reverse=True)
        return [replace(h, score=float(s)) for h, s in reordered[:top_k]]


if __name__ == "__main__":
    import argparse
    import asyncio

    from app.config import get_settings
    from app.db.session import Session
    from app.retrieval.embeddings import get_embedder
    from app.retrieval.hybrid import hybrid_search

    async def main():
        p = argparse.ArgumentParser()
        p.add_argument("--query", required=True)
        p.add_argument("-k", type=int, default=5)
        a = p.parse_args()

        settings = get_settings()
        embedder = get_embedder(settings)
        reranker = Reranker(settings.rerank_model)

        async with Session() as session:
            candidates = await hybrid_search(
                session, a.query, embedder, k=20
            )  # 후보 20개

        print("--- hybrid만 (top", a.k, ") ---")
        for h in candidates[: a.k]:
            print(f"  {h.citation:12} rrf={h.score:.4f} | {h.snippet[:45]}")

        print("--- hybrid + rerank (top", a.k, ") ---")
        for h in reranker.rerank(a.query, candidates, top_k=a.k):
            print(f"  {h.citation:12} ce={h.score:.3f} | {h.snippet[:45]}")

    asyncio.run(main())
