"""File-backed user evaluation sets beside read-only built-in golden JSON."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from pydantic import ValidationError

from app.api.admin_schemas import GoldenCanonicalResource, GoldenRevisionResource, GoldenSuiteId
from app.config import get_settings
from app.evals.admin import SUITES
from app.evals.artifacts import read_strict_json
from app.evals.drafts import (
    DRAFT_CASES,
    DraftConflictError,
    DraftFieldIssue,
    DraftInputError,
    GoldenDraftCase,
    executable_cases,
    unique_draft_ids,
)
from app.evals.loader import (
    GOLDEN_CASES,
    GoldenDataError,
    golden_payload_sha256,
    validate_unique_cases,
)
from app.evals.source_binding import bind_golden


class GoldenAdminService:
    """Store independent datasets atomically beside immutable bundled files."""

    def __init__(self, *, golden_dir: Path | None = None, corpus_dir: Path | None = None) -> None:
        self._golden_dir = (
            golden_dir or Path(__file__).resolve().parents[2] / "data" / "golden"
        ).resolve()
        self._corpus_dir = (corpus_dir or get_settings().corpus_dir).resolve()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize read-modify-write across local workers and refuse a redirected lock."""
        self._golden_dir.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self._golden_dir / ".datasets.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def _path(self, filename: str) -> Path:
        """Accept a flat JSON basename only and reject symlink targets."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\.json", filename):
            raise ValueError(
                "Use a JSON filename containing letters, numbers, dots, dashes or underscores."
            )
        path = self._golden_dir / filename
        if path.is_symlink():
            raise ValueError("Dataset symlinks are not supported")
        return path

    @staticmethod
    def _identity(filename: str) -> int:
        """Keep a stable browser-safe dataset identity independent of database resets."""
        return int(hashlib.sha256(filename.encode()).hexdigest()[:12], 16) or 1

    def _read_user(self, path: Path) -> GoldenRevisionResource:
        """Validate the complete file envelope and reject stale validation claims."""
        raw = read_strict_json(self._path(path.name), error=GoldenDataError)
        if not isinstance(raw, dict) or raw.get("format") != "docreview-golden-set":
            raise GoldenDataError(f"Unsupported user dataset format: {path.name}")
        required = {"suite_id", "cases", "created_at", "updated_at"}
        if (
            not required.issubset(raw)
            or not isinstance(raw["suite_id"], str)
            or raw["suite_id"] not in SUITES
        ):
            raise GoldenDataError(f"Missing or invalid dataset metadata: {path.name}")
        definition = SUITES[raw["suite_id"]]
        if (
            raw.get("registry") != definition.registry
            or raw.get("question_language") != definition.question_language
        ):
            raise GoldenDataError(
                f"Dataset metadata does not match its source configuration: {path.name}"
            )
        if not isinstance(raw["created_at"], str) or not isinstance(raw["updated_at"], str):
            raise GoldenDataError(f"Dataset timestamps must be ISO strings: {path.name}")
        cases = DRAFT_CASES.validate_python(raw["cases"])
        unique_draft_ids(cases)
        payload = [case.model_dump(mode="json") for case in cases]
        digest = golden_payload_sha256(payload)
        return GoldenRevisionResource(
            revision_id=self._identity(path.name),
            filename=path.name,
            file_content=raw,
            completion={
                case.id: [issue.model_dump(mode="json") for issue in case.missing()]
                for case in cases
            },
            suite_id=raw["suite_id"],
            version=1,
            status="validated"
            if raw.get("checked_sha256") == digest
            and cases
            and all(not case.missing() for case in cases)
            else "draft",
            payload=tuple(payload),
            sha256=digest,
            parent_id=None,
            created_at=datetime.fromisoformat(raw["created_at"]),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
        )

    def _write(self, item: GoldenRevisionResource) -> GoldenRevisionResource:
        """Replace one user file atomically; built-in paths are never writable."""
        if item.filename in {definition.golden_name for definition in SUITES.values()}:
            raise ValueError("Built-in datasets are read-only. Create a separate draft.")
        path = self._path(item.filename)
        envelope = {
            "format": "docreview-golden-set",
            "suite_id": item.suite_id,
            "registry": SUITES[item.suite_id].registry,
            "question_language": SUITES[item.suite_id].question_language,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
            "checked_sha256": item.sha256 if item.status == "validated" else None,
            "cases": list(item.payload),
        }
        descriptor, temporary = tempfile.mkstemp(prefix=".dataset-", dir=self._golden_dir)
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(envelope, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self._read_user(path)

    async def list(self, suite_id: GoldenSuiteId) -> tuple[GoldenRevisionResource, ...]:
        """Discover independent user files for the selected source/language configuration."""
        builtins = {definition.golden_name for definition in SUITES.values()}
        rows: list[GoldenRevisionResource] = []
        for path in sorted(self._golden_dir.glob("*.json")):
            if path.name in builtins:
                continue
            try:
                rows.append(self._read_user(path))
            except GoldenDataError, ValueError:
                # A stray or malformed file must not hide every valid dataset; `get`
                # still reports the exact problem when that file is opened directly.
                continue
        return tuple(row for row in rows if row.suite_id == suite_id)

    def get(self, identity: int) -> GoldenRevisionResource:
        """Resolve a stable file identity without reading legacy database revisions."""
        paths = [
            path
            for path in self._golden_dir.glob("*.json")
            if self._identity(path.name) == identity
        ]
        if len(paths) != 1:
            raise ValueError("Dataset file does not exist or its identity is ambiguous")
        return self._read_user(paths[0])

    def canonical(self, suite_id: GoldenSuiteId) -> GoldenCanonicalResource:
        """Read the immutable built-in payload without creating a copy."""
        path = self._path(SUITES[suite_id].golden_name)
        cases = GOLDEN_CASES.validate_python(read_strict_json(path, error=GoldenDataError))
        validate_unique_cases(cases)
        payload = [case.model_dump(mode="json") for case in cases]
        return GoldenCanonicalResource(
            suite_id=suite_id,
            filename=path.name,
            payload=tuple(payload),
            sha256=golden_payload_sha256(payload),
        )

    async def create_draft(
        self,
        suite_id: GoldenSuiteId,
        *,
        filename: str,
        empty: bool = False,
        parent_id: int | None = None,
    ) -> GoldenRevisionResource:
        """Create a named empty dataset or an independent copy of the selected dataset."""
        with self._locked():
            path = self._path(filename)
            if path.exists() or filename in {
                definition.golden_name for definition in SUITES.values()
            }:
                raise ValueError("A dataset with this filename already exists")
            source = self.get(parent_id) if parent_id is not None else self.canonical(suite_id)
            if source.suite_id != suite_id:
                raise ValueError("Source dataset belongs to another suite")
            payload = () if empty else source.payload
            now = datetime.now(UTC)
            item = GoldenRevisionResource(
                revision_id=self._identity(filename),
                filename=filename,
                suite_id=suite_id,
                version=1,
                status="draft",
                payload=payload,
                sha256=golden_payload_sha256(list(payload)),
                parent_id=None,
                created_at=now,
                updated_at=now,
            )
            return self._write(item)

    async def replace_case(
        self, revision_id: int, case_id: str, *, expected_sha256: str, payload: dict[str, object]
    ) -> GoldenRevisionResource:
        """Save or add one strict question with optimistic content concurrency checks."""
        try:
            replacement = GoldenDraftCase.model_validate(payload)
        except ValidationError as error:
            issues = tuple(
                DraftFieldIssue(
                    location=item["loc"],
                    code=item["type"],
                    message="Check this field's type, format, or length.",
                )
                for item in error.errors(include_input=False, include_url=False)
            )
            raise DraftInputError(issues) from error
        if replacement.id != case_id:
            raise ValueError("Case ID must match the request")
        with self._locked():
            item = self.get(revision_id)
            if item.sha256 != expected_sha256:
                raise DraftConflictError(
                    "Dataset changed; reload the saved question before retrying."
                )
            cases = DRAFT_CASES.validate_python(item.payload)
            index = next((i for i, case in enumerate(cases) if case.id == case_id), None)
            if index is None:
                cases.append(replacement)
            else:
                cases[index] = replacement
            unique_draft_ids(cases)
            encoded = tuple(case.model_dump(mode="json") for case in cases)
            return self._write(
                item.model_copy(
                    update={
                        "payload": encoded,
                        "sha256": golden_payload_sha256(list(encoded)),
                        "status": "draft",
                        "updated_at": datetime.now(UTC),
                    }
                )
            )

    async def delete_case(
        self, revision_id: int, case_id: str, *, expected_sha256: str
    ) -> GoldenRevisionResource:
        """Remove one question from a draft with the same optimistic digest check as saving."""
        with self._locked():
            item = self.get(revision_id)
            if item.sha256 != expected_sha256:
                raise DraftConflictError(
                    "Dataset changed; reload the saved question before retrying."
                )
            cases = DRAFT_CASES.validate_python(item.payload)
            remaining = [case for case in cases if case.id != case_id]
            if len(remaining) == len(cases):
                raise ValueError("Question does not exist in this dataset")
            encoded = tuple(case.model_dump(mode="json") for case in remaining)
            return self._write(
                item.model_copy(
                    update={
                        "payload": encoded,
                        "sha256": golden_payload_sha256(list(encoded)),
                        "status": "draft",
                        "updated_at": datetime.now(UTC),
                    }
                )
            )

    async def validate(self, revision_id: int, *, expected_sha256: str) -> GoldenRevisionResource:
        """Check question shape and source spans without granting human quality approval."""
        with self._locked():
            item = self.get(revision_id)
            if item.sha256 != expected_sha256:
                raise DraftConflictError(
                    "Dataset changed; reload the saved question before retrying."
                )
            if not item.payload:
                raise ValueError("Add at least one question before checking")
            executable_cases(item.payload)
            definition = SUITES[item.suite_id]
            bound = bind_golden(
                list(item.payload), self._corpus_dir / definition.manifest_name, definition.registry
            )
            if not bound.ready:
                raise GoldenDataError(
                    "; ".join(
                        source.detail or source.state
                        for source in bound.sources
                        if source.state != "ready"
                    )
                )
            return self._write(
                item.model_copy(update={"status": "validated", "updated_at": datetime.now(UTC)})
            )
