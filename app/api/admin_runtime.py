"""Local-only composition for corpus, evaluation, and profile-preview resources."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import (
    CorpusOperationRequest,
    EvaluationComparisonResponse,
    EvaluationJobResource,
    EvaluationJobsResponse,
    EvaluationRunRequest,
    GoldenSuiteResource,
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    RetrievalProfile,
    ReviewPreviewRequest,
    ReviewPreviewResponse,
)
from app.api.runtime import RuntimeApiServices
from app.api.schemas import EvidenceHit, ReviewRequest, RunResponse
from app.corpus_admin import AdminCommand, RuntimeCorpusAdminService
from app.evals.admin import EvaluationAdminService
from app.evals.arms import make_retriever
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.service import ComponentRankings, RetrievalResult, retrieve
from app.retrieval.types import RetrievalFilters


class RuntimeAdminApiServices:
    """Compose every SSH-only administrator operation without HTTP concerns."""

    def __init__(
        self,
        *,
        runtime: RuntimeApiServices,
        corpus: RuntimeCorpusAdminService | None = None,
        evaluations: EvaluationAdminService | None = None,
    ) -> None:
        self._runtime = runtime
        self._corpus = corpus or RuntimeCorpusAdminService()
        self._evaluations = evaluations or EvaluationAdminService()

    async def corpus_snapshot(self) -> dict[str, Any]:
        """Return one JSON-ready live corpus and index snapshot."""
        return asdict(await self._corpus.snapshot())

    async def document_detail(self, doc_id: str) -> dict[str, Any] | None:
        """Return one bounded document preview when present."""
        detail = await self._corpus.document_detail(doc_id)
        return asdict(detail) if detail is not None else None

    async def enqueue_corpus(self, request: CorpusOperationRequest) -> dict[str, Any]:
        """Queue one validated safe corpus operation."""
        job = await self._corpus.enqueue(
            AdminCommand(
                request.kind,
                identifiers=request.identifiers,
                years=request.years,
                manifest=request.manifest,
                expected_documents=request.expected_documents,
            )
        )
        return asdict(job)

    async def corpus_jobs(self) -> dict[str, Any]:
        """Return JSON-ready corpus queue and history state."""
        return asdict(await self._corpus.jobs())

    async def retry_corpus(self, job_id: str) -> dict[str, Any]:
        """Retry one known failed corpus job."""
        return asdict(await self._corpus.retry(job_id))

    async def suites(self) -> tuple[GoldenSuiteResource, ...]:
        """Return strict golden-suite metadata and source readiness."""
        return await self._evaluations.suites()

    async def enqueue_evaluation(self, request: EvaluationRunRequest) -> EvaluationJobResource:
        """Queue one quick or matrix evaluation."""
        return await self._evaluations.enqueue(request)

    async def evaluation_jobs(self) -> EvaluationJobsResponse:
        """Return newest-first evaluation job state."""
        return await self._evaluations.jobs()

    async def evaluation_job(self, job_id: str) -> EvaluationJobResource | None:
        """Return one evaluation job when known."""
        return await self._evaluations.job(job_id)

    async def compare(
        self,
        candidate_id: int,
        baseline_id: int,
    ) -> EvaluationComparisonResponse:
        """Compare two compatible persisted evaluation artifacts."""
        return await self._evaluations.compare(candidate_id, baseline_id)

    async def _retrieve_profile(
        self,
        session: AsyncSession,
        query: str,
        profile: RetrievalProfile,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        """Execute one explicit profile while retaining component provenance."""
        bm25 = profile.lexical_ranker == "bm25"
        if profile.strategy == "hybrid":
            return await retrieve(
                session,
                query,
                provider=self._runtime.embedding_provider,
                k=profile.k,
                candidate_k=profile.candidate_k,
                filters=filters,
                rrf_k=profile.rrf_k,
                reranker=CrossEncoderReranker() if profile.reranker else None,
                route_by_language=profile.route_by_language,
                lexical_ranker=profile.lexical_ranker,
                bm25_k1=profile.bm25_k1,
                bm25_b=profile.bm25_b,
                bm25_idf=profile.bm25_idf,
            )
        retriever = make_retriever(
            session,
            strategy=profile.strategy,
            provider=self._runtime.embedding_provider,
            lexical_ranker=profile.lexical_ranker,
            bm25_k1=profile.bm25_k1 if bm25 else None,
            bm25_b=profile.bm25_b if bm25 else None,
            bm25_idf=profile.bm25_idf if bm25 else None,
            candidate_k=profile.candidate_k,
            rrf_k=profile.rrf_k,
            route_by_language=profile.route_by_language,
            filters=filters,
        )
        hits = tuple(await retriever(query, profile.k))
        ids = tuple(hit.chunk_id for hit in hits)
        return RetrievalResult(
            hits=hits,
            score_stage="rrf",
            component_rankings=ComponentRankings(
                vector=ids if profile.strategy == "vector" else (),
                lexical=ids if profile.strategy == "lexical" else (),
            ),
        )

    async def retrieval_preview(
        self,
        request: RetrievalPreviewRequest,
    ) -> RetrievalPreviewResponse:
        """Return evidence and component ranks for one session-scoped profile."""
        async with self._runtime.session_factory() as session:
            result = await self._retrieve_profile(
                session,
                request.query,
                request.profile,
                request.filters,
            )
        return RetrievalPreviewResponse(
            query=request.query,
            profile=request.profile,
            score_stage=result.score_stage,
            component_rankings=result.component_rankings.model_dump(mode="python"),
            results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in result.hits),
        )

    async def review_preview(self, request: ReviewPreviewRequest) -> ReviewPreviewResponse:
        """Run an evidence-checked review through one explicit retrieval profile."""

        async def retrieval_override(
            session: AsyncSession,
            query: str,
            _k: int,
            filters: RetrievalFilters,
        ) -> RetrievalResult:
            """Ignore workflow k in favor of the profile's validated cutoff."""
            return await self._retrieve_profile(session, query, request.profile, filters)

        report = await self._runtime.review_with_retrieval(
            ReviewRequest(query=request.query, k=request.profile.k, filters=request.filters),
            retrieval_override,
        )
        return ReviewPreviewResponse(
            profile=request.profile,
            run=RunResponse.from_run_report(report),
        )
