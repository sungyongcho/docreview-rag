"""Database-backed draft, validation, and publication of golden suites."""

from collections.abc import Callable
import os
from pathlib import Path
import tempfile
from typing import cast

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_schemas import GoldenCanonicalResource, GoldenRevisionResource, GoldenSuiteId
from app.config import get_settings
from app.db.models import GoldenRevision
from app.evals.admin import SUITES
from app.evals.artifacts import read_strict_json
from app.evals.loader import (
    GOLDEN_CASES,
    GoldenDataError,
    encode_golden_payload,
    golden_payload_sha256,
    validate_golden_sources,
    validate_unique_cases,
)
from app.evals.types import GoldenCase


def _default_session_factory() -> AsyncSession:
    """Create one caller-owned database session."""
    from app.db.session import Session

    return Session()


class GoldenAdminService:
    """Persist mutable drafts while keeping published revisions immutable."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession] = _default_session_factory,
        golden_dir: Path | None = None,
        corpus_dir: Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        root = Path(__file__).resolve().parents[2]
        self._golden_dir = (golden_dir or root / "data" / "golden").resolve()
        self._corpus_dir = (corpus_dir or get_settings().corpus_dir).resolve()

    def _paths(self, suite_id: GoldenSuiteId) -> tuple[Path, Path]:
        """Resolve one validated suite to its canonical JSON and corpus manifest."""
        definition = SUITES[suite_id]
        return (
            self._golden_dir / definition.golden_name,
            self._corpus_dir / definition.manifest_name,
        )

    @staticmethod
    def _resource(revision: GoldenRevision) -> GoldenRevisionResource:
        """Project one ORM row onto the strict administrator schema."""
        return GoldenRevisionResource(
            revision_id=revision.id,
            suite_id=cast("GoldenSuiteId", revision.suite_id),
            version=revision.version,
            status=cast("str", revision.status),
            payload=tuple(revision.payload),
            sha256=revision.sha256,
            parent_id=revision.parent_id,
            created_at=revision.created_at,
            updated_at=revision.updated_at,
        )

    async def list(self, suite_id: GoldenSuiteId) -> tuple[GoldenRevisionResource, ...]:
        """Return newest-first revisions for one suite."""
        async with self._session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(GoldenRevision)
                    .where(GoldenRevision.suite_id == suite_id)
                    .order_by(GoldenRevision.version.desc())
                )
            )
        return tuple(self._resource(row) for row in rows)

    def canonical(self, suite_id: GoldenSuiteId) -> GoldenCanonicalResource:
        """Return validated canonical cases without creating a database revision."""
        canonical_path, _manifest_path = self._paths(suite_id)
        raw = read_strict_json(canonical_path, error=GoldenDataError)
        if not isinstance(raw, list):
            raise GoldenDataError("canonical golden suite root must be an array")
        cases = GOLDEN_CASES.validate_python(raw)
        validate_unique_cases(cases)
        payload = [case.model_dump(mode="json") for case in cases]
        return GoldenCanonicalResource(
            suite_id=suite_id,
            filename=canonical_path.name,
            payload=tuple(payload),
            sha256=golden_payload_sha256(payload),
        )

    async def create_draft(
        self, suite_id: GoldenSuiteId, *, parent_id: int | None = None
    ) -> GoldenRevisionResource:
        """Create the next draft from canonical JSON or one exact parent revision."""
        canonical_path, _manifest_path = self._paths(suite_id)
        async with self._session_factory() as session:
            parent = await session.get(GoldenRevision, parent_id) if parent_id is not None else None
            if parent_id is not None and (parent is None or parent.suite_id != suite_id):
                raise ValueError("golden parent revision does not belong to this suite")
            raw = (
                parent.payload
                if parent is not None
                else read_strict_json(canonical_path, error=GoldenDataError)
            )
            if not isinstance(raw, list):
                raise GoldenDataError("canonical golden suite root must be an array")
            cases = GOLDEN_CASES.validate_python(raw)
            validate_unique_cases(cases)
            payload = [case.model_dump(mode="json") for case in cases]
            version = (
                int(
                    await session.scalar(
                        select(func.coalesce(func.max(GoldenRevision.version), 0)).where(
                            GoldenRevision.suite_id == suite_id
                        )
                    )
                    or 0
                )
                + 1
            )
            revision = GoldenRevision(
                suite_id=suite_id,
                version=version,
                status="draft",
                payload=payload,
                sha256=golden_payload_sha256(payload),
                parent_id=parent.id if parent is not None else None,
            )
            session.add(revision)
            await session.commit()
            await session.refresh(revision)
        return self._resource(revision)

    async def replace_case(
        self,
        revision_id: int,
        case_id: str,
        *,
        expected_sha256: str,
        payload: dict[str, object],
    ) -> GoldenRevisionResource:
        """Replace one case using optimistic byte-identity concurrency control."""
        try:
            replacement = GoldenCase.model_validate(payload)
        except ValidationError as error:
            raise GoldenDataError(f"invalid golden case: {error}") from error
        if replacement.id != case_id:
            raise ValueError("case id in the path and payload must match")
        async with self._session_factory() as session:
            revision = await session.get(GoldenRevision, revision_id, with_for_update=True)
            if revision is None:
                raise ValueError("golden revision does not exist")
            if revision.status == "published":
                raise ValueError("published golden revisions are immutable")
            if revision.sha256 != expected_sha256:
                raise ValueError("golden draft changed; refresh before saving")
            cases = GOLDEN_CASES.validate_python(revision.payload)
            index = next((i for i, case in enumerate(cases) if case.id == case_id), None)
            if index is None:
                raise ValueError("golden case does not exist in this revision")
            cases[index] = replacement
            validate_unique_cases(cases)
            encoded = [case.model_dump(mode="json") for case in cases]
            revision.payload = encoded
            revision.sha256 = golden_payload_sha256(encoded)
            revision.status = "draft"
            await session.commit()
            await session.refresh(revision)
        return self._resource(revision)

    async def validate(self, revision_id: int, *, expected_sha256: str) -> GoldenRevisionResource:
        """Validate one draft against strict schema, uniqueness, and source spans."""
        async with self._session_factory() as session:
            revision = await session.get(GoldenRevision, revision_id, with_for_update=True)
            if revision is None:
                raise ValueError("golden revision does not exist")
            if revision.sha256 != expected_sha256:
                raise ValueError("golden draft changed; refresh before validating")
            cases = GOLDEN_CASES.validate_python(revision.payload)
            validate_unique_cases(cases)
            _golden_path, manifest_path = self._paths(cast("GoldenSuiteId", revision.suite_id))
            validate_golden_sources(cases, manifest_path)
            revision.status = "validated"
            await session.commit()
            await session.refresh(revision)
        return self._resource(revision)

    async def publish(self, revision_id: int, *, expected_sha256: str) -> GoldenRevisionResource:
        """Atomically replace canonical JSON with one validated revision."""
        async with self._session_factory() as session:
            revision = await session.get(GoldenRevision, revision_id, with_for_update=True)
            if revision is None:
                raise ValueError("golden revision does not exist")
            if revision.status != "validated":
                raise ValueError("golden revision must be validated before publication")
            if revision.sha256 != expected_sha256:
                raise ValueError("golden revision changed; refresh before publishing")
            path, _manifest_path = self._paths(cast("GoldenSuiteId", revision.suite_id))
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as temporary:
                    temporary.write(encode_golden_payload(revision.payload))
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_name, path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
            revision.status = "published"
            await session.commit()
            await session.refresh(revision)
        return self._resource(revision)
