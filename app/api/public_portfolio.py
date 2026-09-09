"""Project existing administrative read models into fixed public preparation counts."""

import asyncio
from datetime import UTC, datetime
from time import monotonic
from typing import Literal

from app.api.document_catalog import DocumentCatalog
from app.api.errors import ApiProblemError
from app.api.public_portfolio_schemas import (
    PublicPortfolioPreparation,
    PublicPortfolioPreparationPair,
)
from app.corpus_admin import RuntimeCorpusAdminService

TARGET_GROUPS: tuple[tuple[Literal["sec", "dart"], str, range], ...] = (
    ("sec", "NVDA", range(2019, 2025)),
    ("sec", "AMD", range(2019, 2025)),
    ("dart", "005930", range(2022, 2025)),
    ("dart", "000660", range(2022, 2025)),
)


def _unavailable() -> ApiProblemError:
    """Keep unknown state distinct from a measured zero and omit internal details."""
    return ApiProblemError(
        status_code=503,
        code="portfolio_preparation_unavailable",
        message="Portfolio preparation counts are temporarily unavailable.",
    )


class PublicPortfolioReader:
    """Read bounded metadata through existing services without exposing their full DTOs."""

    def __init__(self, corpus: RuntimeCorpusAdminService, catalog: DocumentCatalog) -> None:
        self._corpus = corpus
        self._catalog = catalog
        self._lock = asyncio.Lock()
        self._cached: PublicPortfolioPreparation | None = None
        self._measured = 0.0

    async def read(self) -> PublicPortfolioPreparation:
        """Coalesce reads for five seconds; a failed refresh never returns fabricated zeros."""
        async with self._lock:
            if self._cached is not None and monotonic() - self._measured < 5:
                return self._cached
            try:
                result = await self._measure()
            except ApiProblemError:
                raise _unavailable() from None
            except OSError, ValueError:
                raise _unavailable() from None
            self._cached = result
            self._measured = monotonic()
            return result

    async def _measure(self) -> PublicPortfolioPreparation:
        """Combine verified sources with current-provider per-document metadata counts."""
        snapshot = await self._corpus.snapshot()
        if (
            not snapshot.status.database_connected
            or snapshot.status.schema_status != "compatible"
            or any(not manifest.valid for manifest in snapshot.manifests)
        ):
            raise _unavailable()
        totals: dict[tuple[str, str, int], dict[str, int]] = {
            (registry, issuer, year): dict(
                source_documents=0,
                parsed_documents=0,
                chunks=0,
                embedded_chunks=0,
                pending_embeddings=0,
            )
            for registry, issuer, years in TARGET_GROUPS
            for year in years
        }
        for source in snapshot.sources:
            key = (source.registry, source.issuer, source.fiscal_year)
            if key in totals and source.ready:
                totals[key]["source_documents"] += 1
        # The catalog already handles current parse and configured embedding identity.
        # A hard traversal bound refuses unknown totals instead of truncating them.
        cursor = None
        for _ in range(10):
            page = await self._catalog.documents(
                query="",
                registry="",
                issuer="",
                fiscal_year=None,
                language="",
                form="",
                parse_status="",
                embedding_status=None,
                snapshot_id=None,
                sort="doc_id",
                descending=False,
                cursor=cursor,
                limit=100,
            )
            for document in page.documents:
                key = (document.registry, document.issuer, document.fiscal_year)
                if key not in totals:
                    continue
                row = totals[key]
                row["parsed_documents"] += int(document.parse_status == "parsed")
                row["chunks"] += document.chunk_count
                row["embedded_chunks"] += document.embedded_chunks
                row["pending_embeddings"] += max(document.chunk_count - document.embedded_chunks, 0)
            cursor = page.next_cursor
            if cursor is None:
                break
        else:
            raise _unavailable()
        return PublicPortfolioPreparation(
            observed_at=datetime.now(UTC),
            pairs=tuple(
                PublicPortfolioPreparationPair.model_validate(
                    {"registry": registry, "issuer": issuer, "fiscal_year": year, **counts}
                )
                for (registry, issuer, year), counts in totals.items()
            ),
        )
