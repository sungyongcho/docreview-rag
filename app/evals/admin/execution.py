"""Retriever binding, dataset provenance, and the isolated matrix for admin evaluations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import tempfile
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EmbeddingProviderName, Settings
from app.db.session_factory import SessionFactory
from app.evals.admin.preparation import evaluation_cases
from app.evals.contracts import EvaluationRunRequest
from app.evals.execution.evaluator import (
    evaluate_retriever,
    persist_evaluation,
    write_evaluation_artifact,
)
from app.evals.execution.models import EvaluationRetrieval
from app.evals.execution.retrievers import Retriever, make_retriever
from app.evals.experiments.matrix import run_matrix
from app.evals.golden.binding import matrix_scope
from app.evals.golden.catalog import SUITES, suite_paths
from app.evals.golden.loading import encode_golden_payload
from app.evals.golden.models import GoldenCase
from app.evals.golden.store import GoldenAdminService
from app.evals.results.comparison import compatible_baseline
from app.evals.results.identity import artifact_filename, index_fingerprint
from app.retrieval.embedding.provider import EmbeddingProvider
from app.retrieval.ranking.reranker import shared_cross_encoder
from app.retrieval.search.plan import SearchPlan
from app.retrieval.search.profiles import RetrievalProfile
from app.retrieval.search.service import retrieve
from app.retrieval.types import RetrievalFilters


def quick_retriever(
    session: AsyncSession,
    profile: RetrievalProfile,
    filters: RetrievalFilters,
    *,
    provider: EmbeddingProvider,
) -> Retriever:
    """Bind one explicit live-index retrieval profile to the active session."""
    bm25 = profile.lexical_ranker == "bm25"
    if profile.reranker is None:
        return make_retriever(
            session,
            strategy=profile.strategy,
            provider=provider,
            lexical_ranker=profile.lexical_ranker,
            bm25_k1=profile.bm25_k1 if bm25 else None,
            bm25_b=profile.bm25_b if bm25 else None,
            bm25_idf=profile.bm25_idf if bm25 else None,
            candidate_k=profile.candidate_k,
            rrf_k=profile.rrf_k,
            route_by_language=profile.route_by_language,
            filters=filters,
        )
    reranker = shared_cross_encoder()

    async def run(query: str, k: int) -> EvaluationRetrieval:
        """Retrieve and rerank one query with the bound profile."""
        result = await retrieve(
            session,
            query,
            provider=provider,
            k=k,
            plan=SearchPlan(
                candidate_k=profile.candidate_k,
                rrf_k=profile.rrf_k,
                route_by_language=profile.route_by_language,
                lexical_ranker=profile.lexical_ranker or "ts_rank_cd",
                bm25_k1=profile.bm25_k1,
                bm25_b=profile.bm25_b,
                bm25_idf=profile.bm25_idf,
            ),
            filters=filters,
            reranker=reranker,
        )
        return EvaluationRetrieval(hits=result.hits)

    return run


def dataset_provenance(
    request: EvaluationRunRequest, digest: str, *, golden_dir: Path
) -> dict[str, Any]:
    """Freeze the filename and content identity used by this evaluation."""
    filename = (
        SUITES[request.suite_id].golden_name
        if request.golden_revision_id is None
        else GoldenAdminService(golden_dir=golden_dir).get(request.golden_revision_id).filename
    )
    return {
        "filename": filename,
        "dataset_id": f"builtin:{request.suite_id}"
        if request.golden_revision_id is None
        else f"file:{request.golden_revision_id}",
        "kind": "builtin" if request.golden_revision_id is None else "user",
        "verification_status": "pending_review",
        "golden_sha256": digest,
        "golden_revision_id": request.golden_revision_id,
    }


async def run_isolated_matrix(
    request: EvaluationRunRequest,
    cases: Sequence[GoldenCase],
    digest: str,
    *,
    manifest_path: Path,
    golden_dir: Path,
    artifact_dir: Path,
    embedding_provider: EmbeddingProviderName,
) -> dict[str, Any]:
    """Run the existing isolated corpus matrix through its in-process boundary.

    Parameters
    ----------
    request : EvaluationRunRequest
        Matrix request whose axes and retrieval profile are measured.
    cases : Sequence[GoldenCase]
        Source-bound golden cases, written to a temporary golden file for the run.
    digest : str
        Content identity of the golden dataset the cases came from.
    manifest_path : Path
        Corpus manifest the matrix scope is derived from.
    golden_dir : Path
        Directory holding the built-in and user golden files.
    artifact_dir : Path
        Evaluation artifact directory the matrix writes into.
    embedding_provider : EmbeddingProviderName
        Configured embedding provider, which the isolated runner must support.

    Returns
    -------
    dict[str, Any]
        The matrix runner's result.

    Raises
    ------
    ValueError
        If the scope cannot be derived or the embedding provider is unsupported.
    """
    definition = SUITES[request.suite_id]
    scope = await asyncio.to_thread(matrix_scope, manifest_path, definition.registry)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.NamedTemporaryFile(
            mode="w", prefix=".evaluation-scope-", suffix=".json", dir=manifest_path.parent
        ) as scope_file,
        tempfile.NamedTemporaryFile(
            mode="wb", prefix=".golden-bound-", suffix=".json", dir=artifact_dir
        ) as golden_file,
    ):
        scope_file.write(scope.model_dump_json())
        scope_file.flush()
        golden_file.write(encode_golden_payload([case.model_dump(mode="json") for case in cases]))
        golden_file.flush()
        golden_path = Path(golden_file.name)
        if embedding_provider == "sbert":
            raise ValueError("matrix evaluation supports the deterministic and openai providers")
        return await run_matrix(
            suite=request.suite_id,
            golden=golden_path,
            manifest_name=scope_file.name,
            selection_id="evaluation-scope",
            artifact_dir=artifact_dir,
            provider=embedding_provider,
            target_tokens=request.target_tokens,
            strategies=request.strategies,
            lexical_rankers=request.lexical_rankers,
            k=request.profile.k,
            candidate_k=request.profile.candidate_k,
            rrf_k=request.profile.rrf_k,
            bm25_k1=request.profile.bm25_k1,
            bm25_b=request.profile.bm25_b,
            bm25_idf=request.profile.bm25_idf,
            persist_results=True,
            admin_metadata={
                "golden_provenance": dataset_provenance(request, digest, golden_dir=golden_dir),
                "search_scope": {
                    "registry": definition.registry,
                    "document_ids": sorted(document.document_id for document in scope.documents),
                    "manifest_sha256": hashlib.sha256(scope.model_dump_json().encode()).hexdigest(),
                },
            },
        )


async def run_quick(
    request: EvaluationRunRequest,
    *,
    settings: Settings,
    session_factory: SessionFactory,
    provider: EmbeddingProvider,
    golden_dir: Path,
    artifact_dir: Path,
    publish: Callable[..., None],
) -> tuple[int, int | None, Path]:
    """Evaluate one profile against the current populated index and persist evidence."""
    definition = SUITES[request.suite_id]
    publish(stage="golden", message="Validating golden sources", current=0, total=4)
    cases, golden_sha256 = await evaluation_cases(
        request, golden_dir=golden_dir, corpus_dir=settings.corpus_dir
    )
    filters = RetrievalFilters(
        registries=(definition.registry,), languages=(definition.corpus_language,)
    )
    recorded_at = datetime.now(UTC)
    async with session_factory() as session:
        corpus_fingerprint = await index_fingerprint(session, provider.identity)
        baseline = await compatible_baseline(
            session,
            suite=request.suite_id,
            golden_sha256=golden_sha256,
            corpus_fingerprint=corpus_fingerprint,
            k=request.profile.k,
        )
        publish(stage="evaluate", message="Running golden queries", current=1, total=4)
        retriever = quick_retriever(session, request.profile, filters, provider=provider)
        evaluation = await evaluate_retriever(
            cases,
            retriever,
            suite=request.suite_id,
            config={
                "admin_identity": {
                    "golden_sha256": golden_sha256,
                    "golden_revision_id": request.golden_revision_id,
                    "corpus_fingerprint": corpus_fingerprint,
                },
                "golden_provenance": dataset_provenance(
                    request, golden_sha256, golden_dir=golden_dir
                ),
                "search_scope": {
                    "registry": definition.registry,
                    "language": definition.corpus_language,
                    "scope": "current-index",
                },
                "evidence_document_ids": sorted(
                    {answer.doc_id for case in cases for answer in case.answers}
                ),
                "retrieval_profile": request.profile.model_dump(mode="json"),
                "embedding": asdict(provider.identity),
            },
            k=request.profile.k,
            recorded_at=recorded_at,
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / artifact_filename(recorded_at, f"admin-{request.suite_id}")
        publish(stage="artifact", message="Writing evaluation evidence", current=2, total=4)
        write_evaluation_artifact(artifact_path, evaluation)
        persisted = await persist_evaluation(
            session,
            evaluation,
            raw_artifact_path=artifact_path,
        )
        await session.commit()
    publish(stage="persist", message="Persisted evaluation result", current=4, total=4)
    return persisted.result_id, baseline.id if baseline is not None else None, artifact_path


async def run_matrix_request(
    request: EvaluationRunRequest, *, settings: Settings, golden_dir: Path, artifact_dir: Path
) -> dict[str, Any]:
    """Run the existing isolated corpus matrix through its in-process boundary."""
    _golden_path, manifest_path = suite_paths(
        request.suite_id, golden_dir=golden_dir, corpus_dir=settings.corpus_dir
    )
    cases, digest = await evaluation_cases(
        request, golden_dir=golden_dir, corpus_dir=settings.corpus_dir
    )
    return await run_isolated_matrix(
        request,
        cases,
        digest,
        manifest_path=manifest_path,
        golden_dir=golden_dir,
        artifact_dir=artifact_dir,
        embedding_provider=settings.embedding_provider,
    )
