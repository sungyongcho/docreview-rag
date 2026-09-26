"""Public preparation metadata independent of document publication."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.documents.portfolio import PublicPortfolioPreparation, PublicPortfolioReader
from app.api.errors import translate_runtime_errors, unavailable

router = APIRouter(prefix="/public/portfolio", tags=["documents"])


def get_portfolio_reader() -> PublicPortfolioReader:
    """Require an explicitly composed source of measured preparation counts."""
    raise unavailable(
        "portfolio_preparation_unavailable",
        "Portfolio preparation counts require a runtime service.",
    )


@router.get("/preparation", response_model=PublicPortfolioPreparation)
async def preparation(
    reader: Annotated[PublicPortfolioReader, Depends(get_portfolio_reader)],
) -> PublicPortfolioPreparation:
    """Expose only fixed company-year aggregate readiness, never unpublished content."""
    async with translate_runtime_errors():
        return await reader.read()
