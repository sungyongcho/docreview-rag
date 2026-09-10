"""Public preparation metadata independent of document publication."""

from functools import lru_cache

from fastapi import APIRouter

from app.api.deps import Services
from app.api.document_catalog import DocumentCatalog
from app.api.errors import ApiProblemError, translate_runtime_errors
from app.api.public_portfolio import PublicPortfolioReader
from app.api.public_portfolio_schemas import PublicPortfolioPreparation
from app.api.runtime import RuntimeApiServices
from app.config import get_settings
from app.corpus_admin import RuntimeCorpusAdminService

router = APIRouter(prefix="/public/portfolio", tags=["documents"])


@lru_cache(maxsize=8)
def _reader(runtime: RuntimeApiServices) -> PublicPortfolioReader:
    """Reuse read caches and the active provider identity without invoking the provider."""
    settings = get_settings()
    if runtime._corpus_root is not None:
        settings = settings.model_copy(update={"corpus_dir": runtime._corpus_root})
    corpus = RuntimeCorpusAdminService(
        settings=settings,
        session_factory=runtime.session_factory,
        embedding_provider=runtime.embedding_provider,
        corpus_access=runtime.corpus_access,
    )
    catalog = DocumentCatalog(
        runtime.session_factory,
        public_only=False,
        embedding_identity=runtime.embedding_provider.identity,
    )
    return PublicPortfolioReader(corpus, catalog)


@router.get("/preparation", response_model=PublicPortfolioPreparation)
async def preparation(services: Services) -> PublicPortfolioPreparation:
    """Expose only fixed company-year aggregate readiness, never unpublished content."""
    if not isinstance(services, RuntimeApiServices):
        raise ApiProblemError(
            status_code=503,
            code="portfolio_preparation_unavailable",
            message="Portfolio preparation counts require a runtime service.",
        )
    async with translate_runtime_errors():
        return await _reader(services).read()
