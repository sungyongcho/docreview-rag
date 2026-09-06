"""DB 통합 테스트. DB(docker) 연결 안 되면 skip → CI 기본 스위트는 무DB로 돈다.

docker compose up -d db  후에 실행하면 이 테스트가 활성화된다.
"""

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import Chunk, Document
from app.db.reset import reset_schema
from app.db.seed import seed_corpus
from app.db.session import Session, engine
from app.retrieval.embeddings import SentenceTransformerEmbedder
from app.retrieval.types import ChunkHit
from app.retrieval.vector import vector_search


async def _db_reachable() -> bool:
    try:
        async with engine.connect():
            return True
    except Exception:
        return False


async def test_seed_and_vector_search():
    if not await _db_reachable():
        pytest.skip("DB 연결 불가 — `docker compose up -d db` 후 실행")

    # st(384) 명시 — DB 컬럼 Vector(384)와 맞춰야 함. .env 값과 무관하게 고정.
    embedder = SentenceTransformerEmbedder()

    await reset_schema()  # 깨끗한 상태에서 시작
    async with Session() as session:
        await seed_corpus(session, get_settings().seed_dir, embedder)

        n_docs = await session.scalar(select(func.count()).select_from(Document))
        n_chunks = await session.scalar(select(func.count()).select_from(Chunk))
        assert n_docs == 6
        assert n_chunks == 85  # dedup 버그(빈-헤딩 섹션 유실) 회귀 방지

        q_emb = embedder.embed_query("expense reimbursement receipts approval")
        hits = await vector_search(session, q_emb, k=5)

    assert len(hits) == 5
    assert all(isinstance(h, ChunkHit) for h in hits)
    assert hits[0].doc_id == "EXP-001"  # 의미 검색 sanity (경비 질문 → 경비 정책)
    assert all(" §" in h.citation for h in hits)  # 인용 형식 유지
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)  # 점수 내림차순
