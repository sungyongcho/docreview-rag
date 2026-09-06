from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.services import arq_pool
from app.db.models import Run
from app.api.schemas import ReviewRequest

router = APIRouter()


@router.post("/review")
async def review(req: ReviewRequest, session: AsyncSession = Depends(get_session)):
    run_id = str(uuid4())
    session.add(Run(id=run_id, kind="review", status="pending", claim=req.claim))
    await session.commit()
    pool = await arq_pool()
    await pool.enqueue_job("review_job", run_id, req.claim)
    return {"run_id": run_id, "status": "pending"}
