from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.services import embedder
from app.config import get_settings
from app.db.seed import seed_corpus

router = APIRouter()


@router.post("/ingest")
async def ingest(session: AsyncSession = Depends(get_session)):
    n = await seed_corpus(session, get_settings().seed_dir, embedder())
    return {"inserted_chunks": n}
