from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.api.services import close_arq_pool
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_arq_pool()  # arq redis 풀 정리
    await engine.dispose()  # DB 커넥션 풀 정리


app = FastAPI(title="DocReview RAG Agent", lifespan=lifespan)
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
