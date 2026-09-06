from app.llm.provider import MockProvider
from app.llm.schemas import ClaimReport
from app.retrieval.types import ChunkHit
from app.workflow.nodes import check_claim


def _ev(citation: str) -> ChunkHit:
    return ChunkHit("D", "1", "snippet text", 0.9, citation)


def test_no_evidence_is_not_in_docs():
    # 가드레일 1
    report = check_claim("some claim", [], MockProvider())
    assert report.label == "NOT_IN_DOCS"


def test_supported_with_valid_citation():
    evidence = [_ev("HR-001 §2.1")]
    llm = MockProvider(
        ClaimReport(label="SUPPORTED", citations=["HR-001 §2.1"], rationale="mock")
    )
    report = check_claim("claim", evidence, llm)
    assert report.label == "SUPPORTED"
    assert report.citations == ["HR-001 §2.1"]


def test_hallucinated_citation_stripped_and_downgraded():
    # 가드레일 2+3
    evidence = [_ev("HR-001 §2.1")]
    llm = MockProvider(
        ClaimReport(label="SUPPORTED", citations=["FAKE §9.9"], rationale="mock")
    )
    report = check_claim("claim", evidence, llm)
    assert report.citations == []
    assert report.label == "NOT_IN_DOCS"


from langgraph.graph import END

from app.workflow.graph import route_after_check, route_after_grade


def test_route_after_grade():
    assert route_after_grade({"graded_sufficient": True}) == "check"
    assert (
        route_after_grade({"graded_sufficient": False, "retrieve_attempts": 1})
        == "reformulate"
    )
    assert (
        route_after_grade({"graded_sufficient": False, "retrieve_attempts": 2})
        == "handle_missing"
    )


def test_route_after_check_paths():
    assert route_after_check({"error": None}) == END  # 정상 → 끝
    assert route_after_check({"error": "boom", "retries": 0}) == "check"  # 실패 → retry
    assert (
        route_after_check({"error": "boom", "retries": 2}) == "handle_error"
    )  # 소진 → 폴백


def test_fallback_switches_on_primary_failure():
    from app.llm.provider import FallbackProvider, MockProvider
    from app.llm.schemas import ClaimReport

    class _Boom(MockProvider):
        model_name = "boom"

        def structured(self, system, user, schema):
            raise RuntimeError("primary down")

    good = MockProvider(ClaimReport(label="SUPPORTED", citations=[], rationale="ok"))
    good.model_name = "backup"

    fb = FallbackProvider(_Boom(), good)
    out = fb.structured("s", "u", ClaimReport)

    assert out.label == "SUPPORTED"  # 보조가 처리
    assert fb.used_fallback is True
    assert fb.model_name == "backup"  # 트레이스에 보조 모델 기록됨
