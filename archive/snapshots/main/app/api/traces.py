from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.db.models import Trace

router = APIRouter()


@router.get("/traces")
async def list_traces(session: AsyncSession = Depends(get_session), limit: int = 20):
    rows = (
        (await session.execute(select(Trace).order_by(desc(Trace.id)).limit(limit)))
        .scalars()
        .all()
    )
    return [
        {
            "id": t.id,
            "run_id": t.run_id,
            "model": t.model_name,
            "prompt_version": t.prompt_version,
            "latency_ms": t.latency_ms,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "est_cost_usd": t.est_cost_usd,
            "tool_sequence": t.tool_sequence,
            "error": t.error,
        }
        for t in rows
    ]
