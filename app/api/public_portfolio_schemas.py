"""Public preparation counts without unpublished document identities or content."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Count = Annotated[int, Field(ge=0)]


class PublicPortfolioPreparationPair(BaseModel):
    """Aggregate preparation for one fixed portfolio company and fiscal year."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    registry: Literal["sec", "dart"]
    issuer: str
    fiscal_year: int
    source_documents: Count
    parsed_documents: Count
    chunks: Count
    embedded_chunks: Count
    pending_embeddings: Count


class PublicPortfolioPreparation(BaseModel):
    """A measured preparation view; this does not grant publication or search access."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    observed_at: datetime
    pairs: tuple[PublicPortfolioPreparationPair, ...]
