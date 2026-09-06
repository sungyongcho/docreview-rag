import hashlib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EMBED_DIM, Base, Chunk, Document
from app.db.session import Session, engine
from app.ingestion.markdown_parser import parse_corpus
from app.retrieval.embeddings import Embedder


async def create_schema() -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)


async def seed_corpus(session: AsyncSession, seed_dir: Path, embedder: Embedder) -> int:
    # 1) parse_corpus(seed_dir) → sections
    # 2) embedder.embed_documents([heading+content ...])
    # 3) Document upsert(doc_id 기준) + Chunk upsert
    #    중복 방지: content_hash=sha256(content), (doc_id, content_hash) 충돌 시 skip
    #    → postgresql insert(...).on_conflict_do_nothing(index_elements=["doc_id","content_hash"])
    # 반환: 새로 넣은 청크 수
    if embedder.dim != EMBED_DIM:
        raise ValueError(
            f"임베더 dim={embedder.dim} != 컬럼 {EMBED_DIM}. EMBEDDING_PROVIDER=st 인지 확인."
        )

    sections = parse_corpus(seed_dir)
    embeddings = embedder.embed_documents(
        [f"{s.heading}\n{s.content}" for s in sections]
    )

    await session.execute(
        insert(Document)
        .values([{"doc_id": d} for d in {s.doc_id for s in sections}])
        .on_conflict_do_nothing(index_elements=["doc_id"])
    )

    rows = [
        {
            "doc_id": s.doc_id,
            "section": s.section,
            "heading": s.heading,
            "content": s.content,
            "citation": s.citation,
            "content_hash": hashlib.sha256(s.content.encode()).hexdigest(),
            "embedding": emb,
        }
        for s, emb in zip(sections, embeddings)
    ]

    result = await session.execute(
        insert(Chunk)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["doc_id", "section"]  # 인용 = 청크 고유키, 재시드 중복 방지
        )
    )

    await session.commit()
    return result.rowcount


if __name__ == "__main__":
    import asyncio

    from app.config import get_settings
    from app.retrieval.embeddings import get_embedder

    async def main() -> None:
        settings = get_settings()
        await create_schema()
        async with Session() as session:
            inserted = await seed_corpus(
                session, settings.seed_dir, get_embedder(settings)
            )
            n_docs = await session.scalar(select(func.count()).select_from(Document))
            n_chunks = await session.scalar(select(func.count()).select_from(Chunk))
        print(f"documents={n_docs} chunks={n_chunks} inserted={inserted}")

    asyncio.run(main())
