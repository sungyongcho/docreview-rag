from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.schemas import Hit, RetrieveRequest, RetrieveResponse
from app.api.services import embedder, reranker
from app.retrieval.hybrid import hybrid_search

router = APIRouter()


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest, session: AsyncSession = Depends(get_session)):
    if req.rerank:
        candidates = await hybrid_search(session, req.query, embedder(), k=20)
        hits = reranker().rerank(req.query, candidates, top_k=req.k)
    else:
        hits = await hybrid_search(session, req.query, embedder(), k=req.k)
    return RetrieveResponse(query=req.query, results=[Hit(**asdict(h)) for h in hits])
