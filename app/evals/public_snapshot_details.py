"""Read exact public evaluation evidence without evaluation or provider work."""

from typing import Any, Literal

from sqlalchemy import select

from app.api.errors import ApiProblemError
from app.api.public_snapshot_schemas import (
    PublicEvaluationCase,
    PublicGoldenCase,
    PublicSnapshotDataset,
    PublicSnapshotEvaluation,
)
from app.db.models import EvalResult, EvaluationSnapshot, SnapshotChunk
from app.db.session_factory import SessionFactory
from app.evals.artifacts import EvaluationArtifacts, recorded_evaluation_cases
from app.evals.loader import GOLDEN_CASES
from app.evals.types import GoldenCase

MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
PUBLIC_PARAMETERS = frozenset(
    {
        "mode",
        "strategy",
        "bm25_k1",
        "bm25_b",
        "bm25_idf",
        "reranker",
        "k",
        "candidate_k",
        "lexical_ranker",
        "route_by_language",
        "rrf_k",
        "rerank",
        "rerank_top_n",
        "chunk_size",
        "chunk_overlap",
        "coverage_threshold",
        "vector_weight",
        "lexical_weight",
        "score_threshold",
    }
)


def _unavailable() -> ApiProblemError:
    """Avoid exposing storage locations or unpublished identities in failures."""
    return ApiProblemError(
        status_code=409,
        code="snapshot_evidence_unavailable",
        message="The exact published evaluation evidence is unavailable.",
    )


class PublicSnapshotDetails:
    """Use the runtime's existing session and confined artifact boundaries."""

    def __init__(self, session_factory: SessionFactory, artifacts: EvaluationArtifacts):
        self._session_factory = session_factory
        self._artifacts = artifacts

    async def _load(
        self, snapshot_id: int
    ) -> tuple[
        EvaluationSnapshot,
        EvalResult,
        str,
        list[GoldenCase],
        list[dict[str, Any]],
    ]:
        """Validate publication before reading any linked data or files."""
        async with self._session_factory() as session:
            snapshot = await session.get(EvaluationSnapshot, snapshot_id)
            if snapshot is None or not snapshot.public or snapshot.status != "ready":
                raise ApiProblemError(
                    status_code=404,
                    code="snapshot_not_found",
                    message="Published snapshot not found.",
                )
            result = await session.get(EvalResult, snapshot.eval_result_id)
        if result is None:
            raise _unavailable()
        identity = result.config.get("admin_identity")
        digest = identity.get("golden_sha256") if isinstance(identity, dict) else None
        if not isinstance(digest, str) or len(digest) != 64:
            raise _unavailable()
        try:
            artifact = self._artifacts.read(result.raw_artifact_path, max_bytes=MAX_ARTIFACT_BYTES)
            rows = list(
                recorded_evaluation_cases(
                    artifact, suite=result.suite, config=result.config
                ).values()
            )
            cases = GOLDEN_CASES.validate_python([row["golden"] for row in rows])
            async with self._session_factory() as session:
                sources = set(
                    (
                        await session.execute(
                            select(SnapshotChunk.doc_id, SnapshotChunk.source_sha256)
                            .where(SnapshotChunk.snapshot_id == snapshot.id)
                            .distinct()
                        )
                    ).all()
                )
            if any(
                (answer.doc_id, answer.source_sha256) not in sources
                for case in cases
                for answer in case.answers
            ):
                raise _unavailable()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _unavailable() from exc
        return snapshot, result, digest, cases, rows

    @staticmethod
    def _page(
        cases: list[GoldenCase],
        *,
        offset: int,
        limit: int,
        query: str,
        sort: Literal["id", "question"],
    ) -> tuple[int, list[GoldenCase]]:
        """Search the complete verified dataset before stable sorting and paging."""
        if offset < 0 or not 1 <= limit <= 100 or len(query) > 200:
            raise ValueError("Invalid public evidence page")
        needle = query.casefold().strip()
        selected = [case for case in cases if needle in (case.id + " " + case.question).casefold()]
        selected.sort(key=lambda case: (getattr(case, sort).casefold(), case.id))
        return len(selected), selected[offset : offset + limit]

    async def dataset(
        self,
        snapshot_id: int,
        *,
        offset: int = 0,
        limit: int = 50,
        query: str = "",
        sort: Literal["id", "question"] = "id",
    ) -> PublicSnapshotDataset:
        """Expose only exact verified question and answer fields."""
        snapshot, result, digest, cases, _ = await self._load(snapshot_id)
        total, page = self._page(cases, offset=offset, limit=limit, query=query, sort=sort)
        return PublicSnapshotDataset(
            snapshot_id=snapshot.id,
            suite=result.suite,
            golden_sha256=digest,
            total=total,
            offset=offset,
            limit=limit,
            cases=tuple(
                PublicGoldenCase(**case.model_dump(include=set(PublicGoldenCase.model_fields)))
                for case in page
            ),
        )

    async def evaluation(
        self,
        snapshot_id: int,
        *,
        offset: int = 0,
        limit: int = 50,
        query: str = "",
        sort: Literal["id", "question"] = "id",
    ) -> PublicSnapshotEvaluation:
        """Expose allowlisted recorded settings and scores, never raw artifact paths."""
        snapshot, result, _, cases, rows = await self._load(snapshot_id)
        total, page = self._page(cases, offset=offset, limit=limit, query=query, sort=sort)
        by_id = {row["golden"]["id"]: row for row in rows}
        output = []
        try:
            for case in page:
                row = by_id[case.id]
                score = row.get("score") or {}
                output.append(
                    PublicEvaluationCase(
                        case_id=case.id,
                        question=case.question,
                        latency_ms=row["latency_ms"],
                        **{
                            key: score.get(key)
                            for key in (
                                "first_relevant_rank",
                                "recall_at_k",
                                "hit_at_k",
                                "reciprocal_rank",
                            )
                        },
                    )
                )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise _unavailable() from exc
        profile = result.config.get("retrieval_profile", {})
        config = {**result.config, **(profile if isinstance(profile, dict) else {})}
        return PublicSnapshotEvaluation(
            snapshot_id=snapshot.id,
            eval_result_id=result.id,
            suite=result.suite,
            created_at=result.created_at,
            config={
                key: value
                for key, value in config.items()
                if key in PUBLIC_PARAMETERS
                and (value is None or type(value) in (str, int, float, bool))
            },
            metrics=result.metrics,
            total=total,
            offset=offset,
            limit=limit,
            cases=tuple(output),
        )
