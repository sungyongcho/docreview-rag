"""Injected application-service seam for the synchronous HTTP boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Protocol

from fastapi import Depends

from app.api.errors import ApiProblemError
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.ingestion.seed import SeedResult
from app.observability.types import RunReport, StepTrace
from app.retrieval.service import RetrievalResult
from app.workflow.runner import NodeObserver


class ApiServices(Protocol):
    """All domain operations required by the seven HTTP resources."""

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
        """Return ranked evidence without performing HTTP work."""
        ...

    async def list_documents(self) -> Sequence[DocumentResource]:
        """Return document resources in deterministic order."""
        ...

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Run one synchronous local-manifest ingestion operation."""
        ...

    async def review(
        self,
        request: ReviewRequest,
        on_node: NodeObserver | None = None,
    ) -> RunReport:
        """Run and persist one complete evidence-checked workflow.

        ``on_node`` reports each completed node while the run is in flight; the
        synchronous and streamed resources share this one method so a behavior
        change cannot land on one path and miss the other.
        """
        ...

    async def get_run(self, run_id: str) -> RunReport | None:
        """Return one persisted run or null when it does not exist."""
        ...

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Return ordered traces or null when the parent run does not exist."""
        ...

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Return the newest persisted evaluation resources."""
        ...


def get_api_services() -> ApiServices:
    """Require production composition or a test override to inject services."""
    raise ApiProblemError(
        status_code=503,
        code="service_unavailable",
        message="API services are not configured.",
    )


# One dependency alias shared by every route module instead of eight local copies.
Services = Annotated[ApiServices, Depends(get_api_services)]
