from app.evals.loader import RetrievalCase
from app.evals.retrieval_eval import _first_hit_rank, eval_retrieval
from app.retrieval.types import ChunkHit


def _hit(citation: str) -> ChunkHit:
    return ChunkHit("D", "1", "", 0.0, citation)


def test_first_hit_rank():
    hits = [_hit("A §1"), _hit("B §1"), _hit("C §1")]
    assert _first_hit_rank(hits, ["C §1"]) == 3  # C가 3위
    assert (
        _first_hit_rank(hits, ["A §1", "Z §9"]) == 1
    )  # 여러 정답 중 하나라도 → 최상위
    assert _first_hit_rank(hits, ["Z §9"]) is None  # 없으면 None


async def test_eval_retrieval_metrics():
    cases = [
        RetrievalCase("q1", "?", ["A §1"]),  # 정답 1위 → RR=1.0, found
        RetrievalCase("q2", "?", ["Z §9"]),  # top-k에 없음 → RR=0, not found
    ]

    async def retriever(query, k):
        return [_hit("A §1"), _hit("B §1")]  # 항상 A,B 반환

    rep = await eval_retrieval(retriever, cases, k=5)
    assert rep.hit_rate == 0.5  # 2문항 중 1개 found
    assert rep.mrr == 0.5  # (1/1 + 0) / 2


def test_score_claims():
    from app.evals.claim_eval import score_claims

    pairs = [
        ("SUPPORTED", "SUPPORTED"),  # 맞음
        ("NOT_IN_DOCS", "SUPPORTED"),  # 틀림 (지어냄)
        ("CONTRADICTED", "CONTRADICTED"),  # 맞음
    ]
    rep = score_claims(pairs)
    assert rep.accuracy == 2 / 3
    assert rep.confusion["NOT_IN_DOCS"]["SUPPORTED"] == 1
    assert (
        rep.hard_negative_accuracy == 0.5
    )  # NOT_IN_DOCS(틀림)+CONTRADICTED(맞음) = 1/2


def test_score_checklist():
    from app.evals.checklist_eval import score_checklist

    items = [("PASS", "PASS"), ("PASS", "FAIL"), ("FAIL", "FAIL")]  # 2/3
    overall = [("PASS", "FAIL"), ("FAIL", "FAIL")]  # 1/2
    rep = score_checklist(items, overall)
    assert round(rep.item_accuracy, 3) == 0.667
    assert rep.overall_accuracy == 0.5


def test_regression_compare():
    from app.evals.regression import compare

    d = compare({"accuracy": 0.80}, {"accuracy": 0.875})
    assert d["accuracy"]["delta"] == 0.075  # 개선
