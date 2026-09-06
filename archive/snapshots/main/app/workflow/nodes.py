from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.prompts import (
    GRADE_SYSTEM,
    REFORMULATE_SYSTEM,
    SYSTEM,
    build_claim_prompt,
    build_user_prompt,
)
from app.llm.provider import LLMProvider
from app.llm.schemas import ClaimReport, EvidenceGrade, SearchQuery
from app.retrieval.embeddings import Embedder
from app.retrieval.hybrid import hybrid_search
from app.retrieval.rerank import Reranker
from app.retrieval.types import ChunkHit


async def retrieve_evidence(
    session: AsyncSession,
    claim: str,
    embedder: Embedder,
    reranker: Reranker,
    k: int = 5,
) -> list[ChunkHit]:
    candidates = await hybrid_search(session, claim, embedder, k=20)
    return reranker.rerank(claim, candidates, top_k=k)


def check_claim(
    claim: str, evidence: list[ChunkHit], provider: LLMProvider
) -> ClaimReport:
    # 가드레일1 : 근거 없으면 LLM안부르고 NOT_IN_DOCS
    if not evidence:
        return ClaimReport(
            label="NOT_IN_DOCS",
            citations=[],
            rationale="No relevant evidence retrieved.",
        )

    report = provider.structured(
        SYSTEM, build_user_prompt(claim, evidence), ClaimReport
    )

    # 가드레일 2: 지어낸 인용 제거 (실제 검색된 근거만 허용)

    valid = {h.citation for h in evidence}
    report.citations = [c for c in report.citations if c in valid]

    # 가드레일 3: 지지 라벨인데 유효 인용 0개 -> NOT_IN_DOCS강등 (근거 없이 단정 금지)
    if report.label in {"SUPPORTED", "PARTIALLY_SUPPORTED"} and not report.citations:
        report.label = "NOT_IN_DOCS"
        report.rationale += " [guardrail: downgraded — no valid citation]"

    return report


def grade_evidence(claim: str, evidence: list[ChunkHit], provider: LLMProvider) -> bool:
    if not evidence:
        return False
    grade = provider.structured(
        GRADE_SYSTEM, build_user_prompt(claim, evidence), EvidenceGrade
    )
    return grade.sufficient


def reformulate_query(claim: str, provider: LLMProvider) -> str:
    result = provider.structured(
        REFORMULATE_SYSTEM, build_claim_prompt(claim), SearchQuery
    )
    return result.query


if __name__ == "__main__":
    import argparse
    import asyncio

    from app.config import get_settings
    from app.db.session import Session
    from app.llm.provider import get_provider
    from app.retrieval.embeddings import get_embedder

    async def main():
        p = argparse.ArgumentParser()
        p.add_argument("--claim", required=True)
        p.add_argument("-k", type=int, default=5)
        a = p.parse_args()

        settings = get_settings()
        embedder = get_embedder(settings)
        reranker = Reranker(settings.rerank_model)
        provider = get_provider(settings)

        async with Session() as session:
            evidence = await retrieve_evidence(
                session, a.claim, embedder, reranker, k=a.k
            )
            report = check_claim(a.claim, evidence, provider)

        print(f"LABEL     : {report.label}")
        print(f"CITATIONS : {report.citations}")
        print(f"RATIONALE : {report.rationale}")
        print("--- evidence ---")
        for h in evidence:
            print(f"  {h.citation}: {h.snippet[:60]}")

    asyncio.run(main())
