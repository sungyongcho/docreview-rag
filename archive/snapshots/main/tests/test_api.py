"""API 통합 테스트. /health는 무DB, /retrieve는 DB 필요(연결 안 되면 skip)."""

from httpx import ASGITransport, AsyncClient
import pytest

from app.config import get_settings
from app.db.session import engine
from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _db_reachable() -> bool:
    try:
        async with engine.connect():
            return True
    except Exception:
        return False


async def test_health():
    async with _client() as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_retrieve_returns_cited_hits():
    if not await _db_reachable():
        pytest.skip("DB 연결 불가 — `docker compose up -d db`")
    if get_settings().embedding_provider != "st":
        pytest.skip("DB는 Vector(384) — EMBEDDING_PROVIDER=st 필요")

    from app.db.seed import create_schema

    await create_schema()  # 스키마 보장

    async with _client() as client:
        await client.post("/ingest")  # 시드 보장 (idempotent)
        r = await client.post(
            "/retrieve",
            json={"query": "expense reimbursement receipts", "k": 5, "rerank": False},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["query"]
    assert body["results"], "결과 0건"
    assert all(" §" in hit["citation"] for hit in body["results"])  # 인용 형식
    assert any(hit["doc_id"] == "EXP-001" for hit in body["results"])  # 경비 질문 → EXP


async def test_runs_endpoint_get_and_404():
    if not await _db_reachable():
        pytest.skip("DB 연결 불가 — `docker compose up -d db`")

    from uuid import uuid4

    from app.db.models import Run
    from app.db.seed import create_schema
    from app.db.session import Session

    await create_schema()  # runs 테이블 보장
    run_id = str(uuid4())
    async with Session() as session:
        session.add(
            Run(
                id=run_id, kind="review", status="done", claim="c",
                node_path=["retrieve", "check"],
                report={"label": "SUPPORTED"}, error=None,
            )
        )
        await session.commit()

    async with _client() as client:
        r = await client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done"
        assert body["node_path"] == ["retrieve", "check"]  # 노드경로 저장·조회
        assert body["report"]["label"] == "SUPPORTED"

        assert (await client.get("/runs/does-not-exist")).status_code == 404
