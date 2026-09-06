from collections import defaultdict
from dataclasses import dataclass, field

from app.config import get_settings
from app.db.session import Session
from app.evals.loader import ClaimCase, load_claim_golden
from app.llm.provider import get_provider
from app.retrieval.embeddings import get_embedder
from app.retrieval.rerank import Reranker
from app.workflow.nodes import check_claim, retrieve_evidence

LABELS = ["SUPPORTED", "CONTRADICTED", "NOT_IN_DOCS", "PARTIALLY_SUPPORTED"]
HARD = {
    "CONTRADICTED",
    "NOT_IN_DOCS",
    "PARTIALLY_SUPPORTED",
}  # SUPPORTED 아닌 것 = 지어내기 유혹


@dataclass
class ClaimEvalReport:
    accuracy: float
    hard_negative_accuracy: float
    confusion: dict
    per_case: list[dict] = field(default_factory=list)


def score_claims(pairs: list[tuple[str, str]]) -> ClaimEvalReport:
    confusion = {g: defaultdict(int) for g in LABELS}
    correct = hard_total = hard_correct = 0

    for gold, pred in pairs:
        confusion[gold][pred] += 1
        correct += int(pred == gold)
        if gold in HARD:
            hard_total += 1
            hard_correct += int(pred == gold)

    n = len(pairs)
    return ClaimEvalReport(
        accuracy=correct / n if n else 0.0,
        hard_negative_accuracy=hard_correct / hard_total if hard_total else 0.0,
        confusion={g: dict(d) for g, d in confusion.items()},
    )


async def eval_claims(
    session, embeder, reranker, provider, cases: list[ClaimCase]
) -> ClaimEvalReport:
    pairs, per_case = [], []
    for c in cases:
        evidence = await retrieve_evidence(session, c.claim, embeder, reranker)
        report = check_claim(c.claim, evidence, provider)
        pairs.append((c.label, report.label))
        per_case.append(
            {
                "id": c.id,
                "gold": c.label,
                "pred": report.label,
                "ok": report.label == c.label,
            }
        )
    rep = score_claims(pairs)
    rep.per_case = per_case
    return rep


if __name__ == "__main__":
    import asyncio

    async def main():
        settings = get_settings()
        embedder = get_embedder(settings)
        reranker = Reranker(settings.rerank_model)
        provider = get_provider(settings)
        cases = load_claim_golden(settings.dataset_root)

        async with Session() as session:
            rep = await eval_claims(session, embedder, reranker, provider, cases)

        print(
            f"accuracy: {rep.accuracy:.3f}   hard-negative: {rep.hard_negative_accuracy:.3f}   (n={len(cases)})"
        )
        print("confusion (row=gold, col=pred):")
        for g in LABELS:
            print(f"  {g:20} {rep.confusion[g]}")
        for pc in rep.per_case:
            if not pc["ok"]:
                print(f"  ✗ {pc['id']}: gold={pc['gold']} → pred={pc['pred']}")

    asyncio.run(main())
