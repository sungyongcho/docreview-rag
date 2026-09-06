"""DB 스키마 초기화 (드롭 후 재생성). 개발용 — 데이터 다 날아간다.

uv run python -m app.db.reset          # 테이블 드롭 + 재생성
uv run python -m app.db.reset --seed   # 재생성 후 시드까지
"""

import argparse
import asyncio

from app.db.models import Base
from app.db.session import Session, engine


async def reset_schema(seed: bool = False) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.drop_all)  # 있으면 드롭 (FK 순서 자동 정렬)
        await conn.run_sync(Base.metadata.create_all)  # 새 스키마로 재생성
    print("schema reset: dropped + recreated (documents, chunks)")

    if seed:
        from app.config import get_settings
        from app.db.seed import seed_corpus
        from app.retrieval.embeddings import get_embedder

        settings = get_settings()
        async with Session() as session:
            n = await seed_corpus(session, settings.seed_dir, get_embedder(settings))
        print(f"seeded: {n} chunks")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", action="store_true", help="reset 후 바로 시드까지")
    args = p.parse_args()
    asyncio.run(reset_schema(seed=args.seed))
