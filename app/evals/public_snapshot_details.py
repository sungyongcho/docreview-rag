"""Read exact public evaluation evidence without evaluation or provider work."""

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiProblemError
from app.api.public_snapshot_schemas import (
    PublicEvaluationCase,
    PublicGoldenCase,
    PublicSnapshotDataset,
    PublicSnapshotEvaluation,
)
from app.db.models import EvalResult, EvaluationSnapshot, GoldenRevision, SnapshotChunk
from app.evals.admin import SUITES
from app.evals.loader import GOLDEN_CASES, golden_payload_sha256
from app.evals.snapshots import SnapshotService, _golden_sha256
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

    def __init__(self, session_factory: Callable[[], AsyncSession], snapshots: SnapshotService):
        self._session_factory = session_factory
        self._snapshots = snapshots

    async def _load(
        self, snapshot_id: int
    ) -> tuple[
        EvaluationSnapshot,
        EvalResult,
        GoldenRevision | None,
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
            revision = (
                await session.get(GoldenRevision, snapshot.golden_revision_id)
                if snapshot.golden_revision_id is not None
                else None
            )
        if result is None:
            raise _unavailable()
        digest = _golden_sha256(result.config)
        if not isinstance(digest, str) or len(digest) != 64:
            raise _unavailable()
        try:
            # Limit disk work as well as the public page size. The shared reader
            # additionally confines the file to its configured artifact directory.
            if Path(result.raw_artifact_path).stat().st_size > MAX_ARTIFACT_BYTES:
                raise _unavailable()
            artifact = self._snapshots._artifact(result.raw_artifact_path)
            if artifact.get("suite") != result.suite or artifact.get("config") != result.config:
                raise _unavailable()
            rows = artifact.get("cases")
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise _unavailable()
            payload = [row["golden"] for row in rows]
            if golden_payload_sha256(payload) != digest:
                await self._verify_bound_payload(snapshot, result, revision, digest, payload)
            if snapshot.golden_revision_id is not None:
                if (
                    revision is None
                    or revision.status != "published"
                    or revision.sha256 != digest
                    or golden_payload_sha256(revision.payload) != digest
                ):
                    raise _unavailable()
            cases = GOLDEN_CASES.validate_python(payload)
            if len({case.id for case in cases}) != len(cases):
                raise _unavailable()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _unavailable() from exc
        return snapshot, result, revision, digest, cases, rows

    async def _verify_bound_payload(
        self,
        snapshot: EvaluationSnapshot,
        result: EvalResult,
        revision: GoldenRevision | None,
        digest: str,
        payload: list[dict[str, Any]],
    ) -> None:
        """Verify historical alias binding against exact golden bytes and frozen sources."""
        if revision is not None:
            if revision.status != "published" or golden_payload_sha256(revision.payload) != digest:
                raise _unavailable()
            original = revision.payload
        else:
            definition = next((suite for key, suite in SUITES.items() if key == result.suite), None)
            if definition is None:
                raise _unavailable()
            directory = self._snapshots._artifact_dir.parent / "golden"
            path = (directory / definition.golden_name).resolve()
            if path.parent != directory.resolve() or path.stat().st_size > MAX_ARTIFACT_BYTES:
                raise _unavailable()
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise _unavailable()
            original = json.loads(raw)
        originals = GOLDEN_CASES.validate_python(original)
        async with self._session_factory() as session:
            sources = (
                await session.execute(
                    select(
                        SnapshotChunk.doc_id,
                        SnapshotChunk.issuer,
                        SnapshotChunk.fiscal_year,
                        SnapshotChunk.source_sha256,
                    )
                    .where(SnapshotChunk.snapshot_id == snapshot.id)
                    .distinct()
                )
            ).all()
        bound = []
        for case in originals:
            encoded = case.model_dump(mode="json")
            for answer in encoded["answers"]:
                matches = {
                    doc_id
                    for doc_id, issuer, year, sha in sources
                    if answer["doc_id"] in (doc_id, f"{issuer}-FY{year}")
                    and sha == answer["source_sha256"]
                }
                if len(matches) != 1:
                    raise _unavailable()
                answer["doc_id"] = next(iter(matches))
            bound.append(encoded)
        if bound != payload:
            raise _unavailable()

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
        snapshot, result, revision, digest, cases, _ = await self._load(snapshot_id)
        total, page = self._page(cases, offset=offset, limit=limit, query=query, sort=sort)
        return PublicSnapshotDataset(
            snapshot_id=snapshot.id,
            suite=result.suite,
            golden_sha256=digest,
            revision_id=snapshot.golden_revision_id,
            version=revision.version if revision else None,
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
        snapshot, result, _, _, cases, rows = await self._load(snapshot_id)
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
