from dataclasses import dataclass, field

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Chunk
from app.db.session import Session
from app.evals.loader import ChecklistCase, load_checklist_golden
from app.llm.prompts import CHECKLIST_SYSTEM, build_checklist_prompt
from app.llm.provider import get_provider
from app.llm.schemas import ChecklistItemVerdict


@dataclass
class ChecklistReport:
    item_accuracy: float
    overall_accuracy: float
    per_case: list[dict] = field(default_factory=list)


def score_checklist(
    item_pairs: list[tuple], overall_pairs: list[tuple]
) -> ChecklistReport:
    """(expected, pred) 쌍들 → 정확도. 순수 함수(무LLM)."""
    ia = sum(g == p for g, p in item_pairs) / len(item_pairs) if item_pairs else 0.0
    oa = (
        sum(g == p for g, p in overall_pairs) / len(overall_pairs)
        if overall_pairs
        else 0.0
    )
    return ChecklistReport(item_accuracy=ia, overall_accuracy=oa)


async def _requirement_index(session, doc_id: str, sections: list[str]) -> str:
    rows = (
        (
            await session.execute(
                select(Chunk).where(Chunk.doc_id == doc_id, Chunk.section.in_(sections))
            )
        )
        .scalars()
        .all()
    )
    return "\n".join(f"{c.citation}: {c.content}" for c in rows)


async def eval_checklist(
    session, provider, cases: list[ChecklistCase]
) -> ChecklistReport:
    item_pairs, overall_pairs, per_case = [], [], []
    for case in cases:
        preds = []
        for item in case.items:
            req = item["requirement"]
            text = await _requirement_index(session, req["doc_id"], req["sections"])
            v = provider.structured(
                CHECKLIST_SYSTEM,
                build_checklist_prompt(case.scenario, text),
                ChecklistItemVerdict,
            )
            item_pairs.append((item["expected"], v.verdict))
            preds.append(v.verdict)
        overall_pred = "PASS" if all(p == "PASS" for p in preds) else "FAIL"
        overall_pairs.append((case.overall, overall_pred))
        expected = [i["expected"] for i in case.items]
        per_case.append(
            {
                "id": case.id,
                "items_ok": sum(g == p for g, p in zip(expected, preds)),
                "n_items": len(preds),
                "overall_gold": case.overall,
                "overall_pred": overall_pred,
            }
        )
    rep = score_checklist(item_pairs, overall_pairs)
    rep.per_case = per_case
    return rep


if __name__ == "__main__":
    import asyncio

    async def main():
        settings = get_settings()
        provider = get_provider(settings)
        cases = load_checklist_golden(settings.dataset_root)
        async with Session() as session:
            rep = await eval_checklist(session, provider, cases)
        print(
            f"item_accuracy: {rep.item_accuracy:.3f}   overall_accuracy: {rep.overall_accuracy:.3f}   (n={len(cases)})"
        )
        for pc in rep.per_case:
            print(
                f"  {pc['id']}: items {pc['items_ok']}/{pc['n_items']}  overall gold={pc['overall_gold']} pred={pc['overall_pred']}"
            )

    asyncio.run(main())
