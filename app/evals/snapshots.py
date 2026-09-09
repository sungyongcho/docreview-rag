"""Immutable evaluation snapshots over persisted corpus and result identity."""

from collections import defaultdict
from collections.abc import Callable
import hashlib
import json
from pathlib import Path

from sqlalchemy import func, insert, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    SnapshotCaseComparison,
    SnapshotComparisonResponse,
    SnapshotMetricDelta,
    SnapshotResource,
)
from app.db.models import (
    BM25CorpusStat,
    Chunk,
    ChunkEmbedding,
    ChunkLength,
    ChunkTerm,
    Document,
    EvalResult,
    EvaluationSnapshot,
    GoldenRevision,
    LexemeStat,
    SnapshotBM25CorpusStat,
    SnapshotChunk,
    SnapshotChunkLength,
    SnapshotChunkTerm,
    SnapshotDocument,
    SnapshotLexemeStat,
)
from app.db.queries import join_current_parse
from app.evals.admin import SUITES
from app.evals.artifacts import read_strict_json
from app.evals.index_identity import index_fingerprint
from app.retrieval.embeddings import EmbeddingIdentity, matching_embedding


def _default_session_factory() -> AsyncSession:
    """Create one caller-owned session."""
    from app.db.session import Session

    return Session()


def _hash_rows(rows: list[tuple[object, ...]]) -> str:
    """Hash deterministic JSON tuples without depending on database row order."""
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _golden_sha256(config: dict[str, object]) -> object:
    """Read canonical golden identity from quick or legacy evaluation config."""
    identity = config.get("admin_identity")
    if isinstance(identity, dict) and identity.get("golden_sha256") is not None:
        return identity["golden_sha256"]
    return config.get("golden_sha256")


def _cases_by_id(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    """Index persisted artifact case objects by their golden case ID."""
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return {}
    indexed: dict[str, dict[str, object]] = {}
    for item in cases:
        if not isinstance(item, dict) or not isinstance(item.get("golden"), dict):
            continue
        case_id = item["golden"].get("id")
        if isinstance(case_id, str):
            indexed[case_id] = item
    return indexed


def _evaluated_embedding(config: dict[str, object]) -> EmbeddingIdentity:
    """Require the exact vector configuration recorded by the evaluated run."""
    payload = config.get("embedding")
    if not isinstance(payload, dict):
        raise ValueError("evaluation result has no exact embedding identity")
    names = ("provider", "model", "tokenizer")
    if any(not isinstance(payload.get(name), str) or not payload[name].strip() for name in names):
        raise ValueError("evaluation embedding identity is incomplete")
    dimensions = payload.get("dimensions")
    if type(dimensions) is not int or dimensions <= 0:
        raise ValueError("evaluation embedding dimensions must be positive")
    return EmbeddingIdentity(
        payload["provider"], payload["model"], dimensions, payload["tokenizer"]
    )


class SnapshotService:
    """Create and read snapshots without rerunning retrieval or providers."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession] = _default_session_factory,
        artifact_dir: Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._artifact_dir = (
            artifact_dir or Path(__file__).resolve().parents[2] / "data" / "eval_runs"
        ).resolve()

    def _artifact(self, raw: str) -> dict[str, object]:
        """Read one persisted artifact confined to the configured evaluation directory."""
        path = Path(raw).resolve()
        if path.parent != self._artifact_dir:
            raise ValueError("evaluation artifact is outside the configured directory")
        payload = read_strict_json(path, error=ValueError)
        if not isinstance(payload, dict):
            raise ValueError("evaluation artifact root must be an object")
        return payload

    async def _existing(self, eval_result_id: int) -> SnapshotResource | None:
        """Read the snapshot already bound to this result using a fresh transaction."""
        statement = (
            select(EvaluationSnapshot, EvalResult, func.count(SnapshotDocument.doc_id))
            .join(EvalResult, EvalResult.id == EvaluationSnapshot.eval_result_id)
            .outerjoin(SnapshotDocument, SnapshotDocument.snapshot_id == EvaluationSnapshot.id)
            .where(EvaluationSnapshot.eval_result_id == eval_result_id)
            .group_by(EvaluationSnapshot.id, EvalResult.id)
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one_or_none()
        return None if row is None else self._resource(row[0], row[1], int(row[2]))

    async def create(
        self,
        *,
        label: str,
        eval_result_id: int,
        golden_revision_id: int | None,
        public: bool,
    ) -> SnapshotResource:
        """Return an existing snapshot on retry without changing its label or visibility."""
        existing = await self._existing(eval_result_id)
        if existing is not None:
            return existing
        try:
            return await self._create(
                label=label,
                eval_result_id=eval_result_id,
                golden_revision_id=golden_revision_id,
                public=public,
            )
        except IntegrityError as error:
            # Recover only this uniqueness race; every other integrity failure remains an error.
            cause = getattr(error.orig, "__cause__", None)
            constraint = getattr(cause, "constraint_name", None)
            if constraint != "evaluation_snapshots_eval_result_id_key":
                raise
            existing = await self._existing(eval_result_id)
            if existing is None:
                raise
            return existing

    async def _create(
        self,
        *,
        label: str,
        eval_result_id: int,
        golden_revision_id: int | None,
        public: bool,
    ) -> SnapshotResource:
        """Freeze current document and embedding identity around one eval result."""
        async with self._session_factory() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            result = await session.get(EvalResult, eval_result_id)
            if result is None:
                raise ValueError("evaluation result does not exist")
            golden = (
                await session.get(GoldenRevision, golden_revision_id)
                if golden_revision_id is not None
                else None
            )
            if golden_revision_id is not None and (golden is None or golden.status != "published"):
                raise ValueError("snapshot golden revision must be published")
            if golden is not None and _golden_sha256(result.config) != golden.sha256:
                raise ValueError("evaluation result does not match the selected golden revision")
            embedding_identity = _evaluated_embedding(result.config)
            documents = tuple(
                await session.scalars(
                    join_current_parse(select(Document), load=True).order_by(Document.doc_id)
                )
            )
            chunks = (
                await session.execute(
                    select(
                        Chunk.id,
                        Chunk.doc_id,
                        Chunk.source_sha256,
                        ChunkEmbedding.provider,
                        ChunkEmbedding.model,
                        ChunkEmbedding.dimensions,
                        ChunkEmbedding.tokenizer,
                        ChunkEmbedding.embedding,
                    )
                    .outerjoin(ChunkEmbedding, matching_embedding(embedding_identity))
                    .order_by(Chunk.doc_id, Chunk.ordinal)
                )
            ).all()
            corpus_stats = tuple(await session.scalars(select(BM25CorpusStat)))
            lexeme_stats = tuple(await session.scalars(select(LexemeStat)))
            by_document: dict[str, list[tuple[object, ...]]] = defaultdict(list)
            for row in chunks:
                by_document[str(row.doc_id)].append(tuple(row))
            current_fingerprint = await index_fingerprint(session, embedding_identity)
            identity = result.config.get("admin_identity")
            recorded_fingerprint = (
                identity.get("corpus_fingerprint") if isinstance(identity, dict) else None
            )
            if recorded_fingerprint is None:
                raise ValueError("only live-index quick evaluations can become queryable snapshots")
            if recorded_fingerprint != current_fingerprint:
                raise ValueError("evaluation corpus no longer matches the current index")
            snapshot = EvaluationSnapshot(
                label=label.strip(),
                status="ready",
                public=public,
                corpus_fingerprint=current_fingerprint,
                profile=dict(result.config),
                golden_revision_id=golden_revision_id,
                eval_result_id=result.id,
            )
            session.add(snapshot)
            await session.flush()
            for document in documents:
                identity_rows = by_document[document.doc_id]
                session.add(
                    SnapshotDocument(
                        snapshot_id=snapshot.id,
                        doc_id=document.doc_id,
                        source_sha256=document.current_parse.structure.source_sha256,
                        chunk_count=len(identity_rows),
                        embedding_fingerprint=_hash_rows(identity_rows),
                    )
                )
            await session.execute(
                insert(SnapshotChunk).from_select(
                    (
                        "snapshot_id",
                        "chunk_id",
                        "doc_id",
                        "registry",
                        "language",
                        "issuer",
                        "fiscal_year",
                        "form",
                        "item",
                        "kind",
                        "ordinal",
                        "body",
                        "context_header",
                        "index_text",
                        "index_text_sha256",
                        "stable_key",
                        "table_fragment",
                        "text_fragment",
                        "lexical_text",
                        "start_char",
                        "end_char",
                        "source_sha256",
                        "citation",
                        "embedding_provider",
                        "embedding_model",
                        "embedding_dimensions",
                        "embedding_tokenizer",
                        "embedding",
                    ),
                    select(
                        literal(snapshot.id),
                        Chunk.id,
                        Chunk.doc_id,
                        Document.registry,
                        Chunk.language,
                        Document.issuer,
                        Document.fiscal_year,
                        Document.form,
                        Chunk.item,
                        Chunk.kind,
                        Chunk.ordinal,
                        Chunk.body,
                        Chunk.context_header,
                        Chunk.index_text,
                        Chunk.index_text_sha256,
                        Chunk.stable_key,
                        Chunk.table_fragment,
                        Chunk.text_fragment,
                        Chunk.lexical_text,
                        Chunk.start_char,
                        Chunk.end_char,
                        Chunk.source_sha256,
                        Chunk.citation,
                        ChunkEmbedding.provider,
                        ChunkEmbedding.model,
                        ChunkEmbedding.dimensions,
                        ChunkEmbedding.tokenizer,
                        ChunkEmbedding.embedding,
                    )
                    .join(Document, Document.doc_id == Chunk.doc_id)
                    .outerjoin(ChunkEmbedding, matching_embedding(embedding_identity)),
                )
            )
            await session.execute(
                insert(SnapshotChunkTerm).from_select(
                    ("snapshot_id", "chunk_id", "lexeme", "tf"),
                    select(
                        literal(snapshot.id),
                        ChunkTerm.chunk_id,
                        ChunkTerm.lexeme,
                        ChunkTerm.tf,
                    ),
                )
            )
            await session.execute(
                insert(SnapshotChunkLength).from_select(
                    ("snapshot_id", "chunk_id", "dl"),
                    select(literal(snapshot.id), ChunkLength.chunk_id, ChunkLength.dl),
                )
            )
            session.add_all(
                SnapshotBM25CorpusStat(
                    snapshot_id=snapshot.id,
                    language=row.language,
                    n=row.n,
                    avgdl=row.avgdl,
                )
                for row in corpus_stats
            )
            session.add_all(
                SnapshotLexemeStat(
                    snapshot_id=snapshot.id,
                    language=row.language,
                    lexeme=row.lexeme,
                    df=row.df,
                )
                for row in lexeme_stats
            )
            await session.commit()
            await session.refresh(snapshot)
            await session.refresh(result)
        return self._resource(snapshot, result, len(documents))

    async def list(self, *, public_only: bool) -> tuple[SnapshotResource, ...]:
        """Return newest snapshots, optionally confined to public ready rows."""
        statement = (
            select(EvaluationSnapshot, EvalResult, func.count(SnapshotDocument.doc_id))
            .join(EvalResult, EvalResult.id == EvaluationSnapshot.eval_result_id)
            .outerjoin(SnapshotDocument, SnapshotDocument.snapshot_id == EvaluationSnapshot.id)
            .group_by(EvaluationSnapshot.id, EvalResult.id)
            .order_by(EvaluationSnapshot.created_at.desc(), EvaluationSnapshot.id.desc())
        )
        if public_only:
            statement = statement.where(
                EvaluationSnapshot.public.is_(True), EvaluationSnapshot.status == "ready"
            )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            self._resource(snapshot, result, int(count)) for snapshot, result, count in rows
        )

    async def set_public(self, snapshot_id: int, *, public: bool) -> SnapshotResource:
        """Change only visibility while retaining immutable experiment identity."""
        async with self._session_factory() as session:
            snapshot = await session.get(EvaluationSnapshot, snapshot_id, with_for_update=True)
            if snapshot is None:
                raise ValueError("evaluation snapshot does not exist")
            if snapshot.status != "ready":
                raise ValueError("only ready snapshots can change visibility")
            snapshot.public = public
            result = await session.get(EvalResult, snapshot.eval_result_id)
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(SnapshotDocument)
                    .where(SnapshotDocument.snapshot_id == snapshot.id)
                )
                or 0
            )
            await session.commit()
            await session.refresh(snapshot)
        assert result is not None
        return self._resource(snapshot, result, count)

    async def compare(
        self, baseline_id: int, candidate_id: int, *, public_only: bool = False
    ) -> SnapshotComparisonResponse:
        """Compare stored metrics without running retrieval or a provider."""
        async with self._session_factory() as session:
            snapshots = {
                item.id: item
                for item in await session.scalars(
                    select(EvaluationSnapshot).where(
                        EvaluationSnapshot.id.in_((baseline_id, candidate_id))
                    )
                )
            }
            baseline = snapshots.get(baseline_id)
            candidate = snapshots.get(candidate_id)
            if baseline is None or candidate is None:
                raise ValueError("snapshot comparison requires two existing snapshots")
            if public_only and (
                not baseline.public
                or not candidate.public
                or baseline.status != "ready"
                or candidate.status != "ready"
            ):
                raise ValueError("public comparison requires two published ready snapshots")
            results = {
                item.id: item
                for item in await session.scalars(
                    select(EvalResult).where(
                        EvalResult.id.in_((baseline.eval_result_id, candidate.eval_result_id))
                    )
                )
            }
        before = results[baseline.eval_result_id]
        after = results[candidate.eval_result_id]
        before_golden = baseline.golden_revision_id or _golden_sha256(before.config)
        after_golden = candidate.golden_revision_id or _golden_sha256(after.config)
        comparable = before.suite == after.suite and before_golden == after_golden
        names = sorted(set(before.metrics) | set(after.metrics))
        metrics = tuple(
            SnapshotMetricDelta(
                name=name,
                baseline=float(before.metrics.get(name, 0)),
                candidate=float(after.metrics.get(name, 0)),
                delta=(
                    float(after.metrics.get(name, 0)) - float(before.metrics.get(name, 0))
                    if comparable
                    else None
                ),
            )
            for name in names
        )
        before_cases = _cases_by_id(self._artifact(before.raw_artifact_path))
        after_cases = _cases_by_id(self._artifact(after.raw_artifact_path))
        common_ids = sorted(set(before_cases) & set(after_cases))
        cases: list[SnapshotCaseComparison] = []
        for case_id in common_ids:
            baseline_case = before_cases[case_id]
            candidate_case = after_cases[case_id]
            baseline_golden = baseline_case["golden"]
            candidate_golden = candidate_case["golden"]
            assert isinstance(baseline_golden, dict)
            assert isinstance(candidate_golden, dict)
            baseline_score = baseline_case.get("score")
            candidate_score = candidate_case.get("score")
            baseline_rank = (
                baseline_score.get("first_relevant_rank")
                if isinstance(baseline_score, dict)
                else None
            )
            candidate_rank = (
                candidate_score.get("first_relevant_rank")
                if isinstance(candidate_score, dict)
                else None
            )
            transition = (
                "stable_miss"
                if baseline_rank is None and candidate_rank is None
                else "miss_to_hit"
                if baseline_rank is None
                else "hit_to_miss"
                if candidate_rank is None
                else "stable_hit"
            )
            cases.append(
                SnapshotCaseComparison(
                    case_id=case_id,
                    baseline_question=str(baseline_golden.get("question", case_id)),
                    candidate_question=str(candidate_golden.get("question", case_id)),
                    baseline_rank=baseline_rank,
                    candidate_rank=candidate_rank,
                    transition=transition,
                    rank_delta=(
                        int(candidate_rank) - int(baseline_rank)
                        if comparable and baseline_rank is not None and candidate_rank is not None
                        else None
                    ),
                )
            )
        return SnapshotComparisonResponse(
            baseline_id=baseline_id,
            candidate_id=candidate_id,
            directly_comparable=comparable,
            warning=(
                None
                if comparable
                else "Golden suite identities differ; metric deltas are intentionally hidden."
            ),
            metrics=metrics,
            common_case_count=len(cases),
            cases=tuple(cases),
        )

    @staticmethod
    def _resource(
        snapshot: EvaluationSnapshot, result: EvalResult, document_count: int
    ) -> SnapshotResource:
        """Project ORM rows onto the public strict snapshot resource."""
        return SnapshotResource.model_validate(
            {
                "snapshot_id": snapshot.id,
                "label": snapshot.label,
                "status": snapshot.status,
                "public": snapshot.public,
                "corpus_fingerprint": snapshot.corpus_fingerprint,
                "profile": snapshot.profile,
                "golden_revision_id": snapshot.golden_revision_id,
                "eval_result": {
                    "result_id": result.id,
                    "suite": result.suite,
                    "config": result.config,
                    "metrics": {name: float(value) for name, value in result.metrics.items()},
                    "raw_artifact_path": result.raw_artifact_path,
                    "created_at": result.created_at,
                },
                "suite_title": (SUITES[result.suite].title if result.suite in SUITES else None),
                "document_count": document_count,
                "created_at": snapshot.created_at,
            }
        )
