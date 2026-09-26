"""Bind evaluation evidence and report the readiness of the current corpus."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.corpus_admin.types import CorpusStatus
from app.db.models import Chunk
from app.db.session_factory import SessionFactory
from app.evals.contracts import EvaluationPreparationResource, EvaluationRunRequest
from app.evals.golden.binding import BoundGolden, bind_golden, matrix_scope
from app.evals.golden.catalog import SUITES, golden_file_sha256, suite_paths
from app.evals.golden.models import DraftInputError, GoldenCase, GoldenDataError, executable_cases
from app.evals.golden.store import GoldenAdminService
from app.evals.results.artifacts import read_strict_json


async def bound_golden(
    request: EvaluationRunRequest, *, golden_dir: Path, corpus_dir: Path
) -> tuple[BoundGolden, str]:
    """Read the chosen dataset and bind its exact evidence to acquired sources."""
    golden_path, manifest_path = suite_paths(
        request.suite_id, golden_dir=golden_dir, corpus_dir=corpus_dir
    )
    if request.golden_revision_id is None:
        payload = read_strict_json(golden_path, error=GoldenDataError)
        digest = golden_file_sha256(golden_path)
    else:
        revision = GoldenAdminService(golden_dir=golden_dir).get(request.golden_revision_id)
        if revision.suite_id != request.suite_id:
            raise GoldenDataError("golden revision does not belong to the requested suite")
        executable_cases(revision.payload)
        payload, digest = list(revision.payload), revision.sha256
    if not payload:
        raise GoldenDataError("Add at least one question before evaluating")
    bound = await asyncio.to_thread(
        bind_golden, payload, manifest_path, SUITES[request.suite_id].registry
    )
    return bound, digest


async def evaluation_cases(
    request: EvaluationRunRequest, *, golden_dir: Path, corpus_dir: Path
) -> tuple[list[GoldenCase], str]:
    """Require every chosen source before returning executable evaluation cases."""
    bound, digest = await bound_golden(request, golden_dir=golden_dir, corpus_dir=corpus_dir)
    if not bound.ready:
        raise GoldenDataError(
            "; ".join(
                source.detail or source.state for source in bound.sources if source.state != "ready"
            )
        )
    return list(bound.cases), digest


async def missing_parsed_sources(
    cases: tuple[GoldenCase, ...], session_factory: SessionFactory
) -> set[tuple[str, str]]:
    """Compare exact required document versions with the indexed source versions."""
    expected = {
        (answer.doc_id, str(answer.source_sha256)) for case in cases for answer in case.answers
    }
    if not expected:
        return set()
    async with session_factory() as session:
        found = set(
            (
                await session.execute(
                    select(Chunk.doc_id, Chunk.source_sha256)
                    .where(Chunk.doc_id.in_({doc_id for doc_id, _ in expected}))
                    .distinct()
                )
            ).all()
        )
    return expected - found


def require_index(request: EvaluationRunRequest, status: CorpusStatus) -> None:
    """Require the storage and search lanes actually used by this evaluation."""
    if not status.writable:
        raise ValueError("Evaluation requires writable source storage.")
    if request.profile.strategy in {"hybrid", "vector"} and status.pending_embeddings > 0:
        raise ValueError("Complete embeddings before evaluation (step 3).")
    if (
        request.profile.strategy in {"hybrid", "lexical"}
        and request.profile.lexical_ranker == "bm25"
        and not status.bm25_ready
    ):
        raise ValueError("Compute BM25 before evaluation (step 4).")


async def prepare_evaluation(
    request: EvaluationRunRequest,
    *,
    golden_dir: Path,
    corpus_dir: Path,
    session_factory: SessionFactory,
    corpus_status: Callable[[], Awaitable[CorpusStatus]] | None,
) -> EvaluationPreparationResource:
    """Report source, parsing and index readiness without registering a job."""
    base: dict[str, Any] = {
        "suite_id": request.suite_id,
        "kind": "builtin" if request.golden_revision_id is None else "user",
    }
    try:
        bound, digest = await bound_golden(request, golden_dir=golden_dir, corpus_dir=corpus_dir)
    except DraftInputError as error:
        return EvaluationPreparationResource(
            **base,
            state="draft_incomplete",
            blockers=tuple(issue.message for issue in error.issues),
        )
    except (OSError, ValueError) as error:
        return EvaluationPreparationResource(
            **base, state="source_invalid", next_step="filings", blockers=(str(error),)
        )
    except SQLAlchemyError:
        return EvaluationPreparationResource(
            **base,
            state="unavailable",
            next_step="setup",
            blockers=("Evaluation preparation status is unavailable.",),
        )
    base.update(source_checks=bound.sources, golden_sha256=digest)
    failed = [source for source in bound.sources if source.state != "ready"]
    if failed:
        return EvaluationPreparationResource(
            **base,
            state="source_invalid"
            if any(source.state == "source_invalid" for source in failed)
            else "source_missing",
            next_step="filings",
            blockers=tuple(
                f"{source.issuer} FY{source.fiscal_year}: {source.detail}" for source in failed
            ),
        )
    if corpus_status is None:
        return EvaluationPreparationResource(
            **base,
            state="unavailable",
            next_step="setup",
            blockers=("Evaluation preparation status is unavailable.",),
        )
    status = None
    try:
        status = await corpus_status()
        if not status.database_connected or status.schema_status != "compatible":
            return EvaluationPreparationResource(
                **base,
                state="unavailable",
                next_step="setup",
                blockers=("Evaluation requires a compatible database.",),
            )
        if request.mode == "matrix":
            if not status.writable:
                return EvaluationPreparationResource(
                    **base,
                    state="unavailable",
                    next_step="setup",
                    blockers=(
                        "Evaluation requires a compatible database and writable source storage.",
                    ),
                )
            await asyncio.to_thread(
                matrix_scope,
                corpus_dir / SUITES[request.suite_id].manifest_name,
                SUITES[request.suite_id].registry,
            )
        else:
            if not status.chunks:
                return EvaluationPreparationResource(
                    **base,
                    state="parsing_required",
                    next_step="index",
                    blockers=("Parse and chunk the required originals before evaluation.",),
                )
            missing = await missing_parsed_sources(bound.cases, session_factory)
            if missing:
                return EvaluationPreparationResource(
                    **base,
                    state="parsing_required",
                    next_step="index",
                    blockers=tuple(
                        f"Parse and chunk the required original: {doc_id}"
                        for doc_id, _ in sorted(missing)
                    ),
                )
            require_index(request, status)
    except ValueError as error:
        if request.mode == "matrix":
            return EvaluationPreparationResource(
                **base, state="source_invalid", next_step="filings", blockers=(str(error),)
            )
        if status is None:
            return EvaluationPreparationResource(
                **base,
                state="unavailable",
                next_step="setup",
                blockers=("Evaluation preparation status is unavailable.",),
            )
        return EvaluationPreparationResource(
            **base,
            state="index_update_required",
            blockers=(str(error),),
        )
    except OSError as error:
        if request.mode == "matrix":
            return EvaluationPreparationResource(
                **base, state="source_invalid", next_step="filings", blockers=(str(error),)
            )
        return EvaluationPreparationResource(
            **base,
            state="unavailable",
            next_step="setup",
            blockers=("Evaluation preparation status is unavailable.",),
        )
    except SQLAlchemyError:
        return EvaluationPreparationResource(
            **base,
            state="unavailable",
            next_step="setup",
            blockers=("Evaluation preparation status is unavailable.",),
        )
    return EvaluationPreparationResource(**base, state="ready")
