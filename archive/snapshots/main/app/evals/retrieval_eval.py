from dataclasses import dataclass, field

from app.config import get_settings
from app.db.session import Session
from app.evals.loader import RetrievalCase, load_retrieval_golden
from app.retrieval.embeddings import get_embedder
from app.retrieval.hybrid import hybrid_search
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import Reranker
from app.retrieval.types import ChunkHit
from app.retrieval.vector import vector_search


@dataclass
class RetrievalReport:
    hit_rate: float
    mrr: float
    per_case: list[dict] = field(default_factory=list)


def _first_hit_rank(retrieved: list[ChunkHit], expected: list[str]) -> int | None:
    exp = set(expected)
    for rank, hit in enumerate(retrieved, start=1):
        if hit.citation in exp:
            return rank
    return None


async def eval_retrieval(
    retriever, cases: list[RetrievalCase], k: int = 5
) -> RetrievalReport:
    hits = 0
    rr_sum = 0.0
    per_case = []
    for case in cases:
        retrieved = await retriever(case.question, k)
        rank = _first_hit_rank(retrieved, case.expected_citations)
        found = rank is not None
        hits += int(found)
        rr_sum += (1.0 / rank) if found else 0.0
        per_case.append(
            {
                "id": case.id,
                "expected": case.expected_citations,
                "found": found,
                "rank": rank,
            }
        )
    n = len(cases)
    return RetrievalReport(hits / n, rr_sum / n, per_case)


if __name__ == "__main__":
    import asyncio

    async def main():
        settings = get_settings()
        embedder = get_embedder(settings)
        reranker = Reranker(settings.rerank_model)
        cases = load_retrieval_golden(settings.dataset_root)

        async with Session() as session:

            async def vector(q, k):
                return await vector_search(session, embedder.embed_query(q), k=k)

            async def lexical(q, k):
                return await lexical_search(session, q, k=k)

            async def hybrid(q, k):
                return await hybrid_search(session, q, embedder, k=k)

            async def hybrid_rerank(q, k):
                cand = await hybrid_search(session, q, embedder, k=20)
                return reranker.rerank(q, cand, top_k=k)

            configs = [
                ("vector", vector),
                ("lexical", lexical),
                ("hybrid", hybrid),
                ("hybrid+rerank", hybrid_rerank),
            ]

            print(f"{'config':16}{'hit_rate':>10}{'mrr':>8}  (k=5, n={len(cases)})")
            for name, r in configs:  # 이름은 호출부에서 관리
                rep = await eval_retrieval(r, cases, k=5)
                print(f"{name:16}{rep.hit_rate:>10.3f}{rep.mrr:>8.3f}")

    asyncio.run(main())
