"""Retriever binding, dataset provenance, and the isolated matrix for admin evaluations."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import hashlib
from pathlib import Path
import tempfile
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import EvaluationRunRequest, RetrievalProfile
from app.config import EmbeddingProviderName
from app.evals.arms import Retriever, make_retriever
from app.evals.golden_admin import GoldenAdminService
from app.evals.loader import encode_golden_payload
from app.evals.run import run_matrix
from app.evals.source_binding import matrix_scope
from app.evals.suites import SUITES
from app.evals.types import EvaluationRetrieval, GoldenCase
from app.retrieval.cross_encoder import shared_cross_encoder
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.service import retrieve
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
            candidate_k=profile.candidate_k,
            filters=filters,
            rrf_k=profile.rrf_k,
            reranker=reranker,
            route_by_language=profile.route_by_language,
            lexical_ranker=profile.lexical_ranker or "ts_rank_cd",
            bm25_k1=profile.bm25_k1,
            bm25_b=profile.bm25_b,
            bm25_idf=profile.bm25_idf,
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
