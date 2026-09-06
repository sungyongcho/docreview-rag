from functools import lru_cache

from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings
from app.retrieval.embeddings import Embedder, get_embedder
from app.retrieval.rerank import Reranker


@lru_cache
def embedder() -> Embedder:
    return get_embedder(get_settings())


@lru_cache
def reranker() -> Reranker:
    return Reranker(get_settings().rerank_model)


_pool = None


async def arq_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
