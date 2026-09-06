from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.db.models import Chunk, Document

router = APIRouter()


@router.get("/documents")
async def list_documents(session: AsyncSession = Depends(get_session)):
    statement = (
        select(Document.doc_id, Document.title, Document.version, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
        .group_by(Document.doc_id, Document.title, Document.version)
        .order_by(Document.doc_id)
    )
    rows = (await session.execute(statement)).all()
    return [
        {"doc_id": d, "title": t, "version": v, "section_count": c}
        for d, t, v, c in rows
    ]
