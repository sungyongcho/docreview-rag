"""Load strict golden cases and bind every positive span to the raw corpus."""

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from pydantic import TypeAdapter, ValidationError

from app.evals.types import GoldenCase

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "retrieval.json"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "corpus" / "manifest.json"
GOLDEN_CASES = TypeAdapter(list[GoldenCase])


class GoldenDataError(ValueError):
    """A golden file or its cited source snapshot violates the M3 contract."""


def _read_json(path: Path) -> object:
    """Read one UTF-8 JSON file, rejecting duplicate keys instead of merging them.

    Parameters
    ----------
    path : Path
        JSON file to read.

    Returns
    -------
    object
        Parsed JSON value; callers narrow the expected root type themselves.

    Raises
    ------
    GoldenDataError
        If the file cannot be read as UTF-8 JSON or contains a duplicate key.

    Notes
    -----
    Duplicate keys are only visible in the ``object_pairs_hook`` before pairs
    merge into a dictionary; after parsing the loss would be silent.
    """

    def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Merge pairs into a dict, failing on any repeated key."""
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise GoldenDataError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except GoldenDataError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldenDataError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _golden_files(path: Path) -> list[Path]:
    """Return the golden files behind one path, rejecting an empty directory."""
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise GoldenDataError(f"no golden JSON files found in {path}")
        return files
    return [path]


def _validate_unique_cases(cases: Iterable[GoldenCase]) -> None:
    """Reject id, question, and answer-identity duplicates across the batch.

    Parameters
    ----------
    cases : Iterable[GoldenCase]
        Cases from every loaded golden file, checked as one batch.

    Raises
    ------
    GoldenDataError
        If two cases share an id, a casefolded whitespace-normalized question,
        or one exact answer-span identity.

    Notes
    -----
    Span identity is compared across cases; duplicates inside one case are
    already rejected by ``GoldenCase`` itself.
    """
    ids: set[str] = set()
    questions: set[str] = set()
    answer_identities: set[tuple[str, str, int, int]] = set()

    for case in cases:
        if case.id in ids:
            raise GoldenDataError(f"duplicate golden case id: {case.id}")
        ids.add(case.id)

        normalized = " ".join(case.question.casefold().split())
        if normalized in questions:
            raise GoldenDataError(f"duplicate normalized question: {case.question}")
        questions.add(normalized)

        for answer in case.answers:
            identity = (
                answer.doc_id,
                answer.source_sha256,
                answer.start_char,
                answer.end_char,
            )

            if identity in answer_identities:
                raise GoldenDataError(f"duplicate answer span identity in {case.id}")
            answer_identities.add(identity)


def _resolve_source_path(file_name: str, manifest_path: Path) -> Path:
    """Return the existing file behind one manifest ``file`` entry.

    Parameters
    ----------
    file_name : str
        Absolute or repository-relative path recorded in the manifest.

    manifest_path : Path
        Manifest location whose parents anchor relative entries.

    Returns
    -------
    Path
        First existing candidate file.

    Raises
    ------
    GoldenDataError
        If no candidate resolves to an existing file.

    Notes
    -----
    Candidates are tried in a fixed order — current directory, repository
    root, then the manifest's parents — so resolution does not depend on the
    process working directory alone.
    """
    source = Path(file_name)
    if source.is_absolute() and source.is_file():
        return source

    bases = [Path.cwd(), REPO_ROOT, manifest_path.resolve().parent]
    bases.extend(manifest_path.resolve().parents)
    for base in bases:
        candidate = (base / source).resolve()
        if candidate.is_file():
            return candidate
    raise GoldenDataError(f"manifest source file does not exist: {file_name}")


def _manifest_sources(manifest_path: Path) -> dict[str, Path]:
    """Map each manifest document id to its resolved source file.

    Parameters
    ----------
    manifest_path : Path
        Corpus manifest listing ticker, report date, and file per document.

    Returns
    -------
    dict[str, Path]
        ``TICKER-FYyyyy`` document ids mapped to existing source files.

    Raises
    ------
    GoldenDataError
        If the manifest root is not an array, an entry is malformed, or two
        entries produce the same document id.
    """
    payload = _read_json(manifest_path)
    if not isinstance(payload, list):
        raise GoldenDataError("corpus manifest root must be a JSON array")

    sources: dict[str, Path] = {}
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise GoldenDataError(f"manifest entry {index} must be an object")
        try:
            ticker = entry["ticker"]
            report_date = entry["report_date"]
            file_name = entry["file"]
        except KeyError as exc:
            raise GoldenDataError(f"manifest entry {index} is missing {exc.args[0]}") from exc

        if not all(isinstance(value, str) and value for value in (ticker, report_date, file_name)):
            raise GoldenDataError(f"manifest entry {index} has invalid identity fields")
        if len(report_date) < 4 or not report_date[:4].isdigit():
            raise GoldenDataError(f"manifest entry {index} has an invalid report_date")

        doc_id = f"{ticker}-FY{report_date[:4]}"
        if doc_id in sources:
            raise GoldenDataError(f"duplicate manifest document id: {doc_id}")
        sources[doc_id] = _resolve_source_path(file_name, manifest_path)
    return sources


def validate_golden_sources(
    cases: Iterable[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> None:
    """Verify each positive span against its exact UTF-8 source and SHA-256.

    Parameters
    ----------
    cases : Iterable[GoldenCase]
        Cases whose positive answer spans are checked against the corpus.

    manifest_path : str | Path
        Corpus manifest used to resolve each cited document id.

    Raises
    ------
    GoldenDataError
        If a span cites an unknown document, its snapshot hash does not match,
        its interval leaves the document, or it contains no visible text.

    Notes
    -----
    Source bytes are hashed before UTF-8 decoding so the coordinate system
    cannot drift with decoding choices. Bytes are read and hashed once per
    document, while the hash, bounds, and visibility gates run per span.
    """
    sources = _manifest_sources(Path(manifest_path))
    cache: dict[str, tuple[str, str]] = {}

    for case in cases:
        for answer in case.answers:
            source_path = sources.get(answer.doc_id)
            if source_path is None:
                raise GoldenDataError(f"{case.id} cites unknown corpus document {answer.doc_id}")

            if answer.doc_id not in cache:
                try:
                    source_byte = source_path.read_bytes()
                    raw_source = source_byte.decode("utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    raise GoldenDataError(
                        f"cannot read UTF-8 source for {answer.doc_id}: {exc}"
                    ) from exc
                cache[answer.doc_id] = (raw_source, hashlib.sha256(source_byte).hexdigest())

            raw_source, source_sha256 = cache[answer.doc_id]
            if answer.source_sha256 != source_sha256:
                raise GoldenDataError(f"{case.id} source hash does not match {answer.doc_id}")
            if answer.end_char > len(raw_source):
                raise GoldenDataError(
                    f"{case.id} span ends beyond {answer.doc_id}: "
                    f"{answer.end_char} > {len(raw_source)}"
                )
            evidence = BeautifulSoup(
                raw_source[answer.start_char : answer.end_char],
                "html.parser",
            ).get_text(" ", strip=True)
            if not evidence:
                raise GoldenDataError(
                    f"{case.id} span has no visible source evidence in {answer.doc_id}"
                )


def load_golden_cases(
    path: str | Path = DEFAULT_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[GoldenCase]:
    """Load one file or a directory of files and validate all source citations.

    Parameters
    ----------
    path : str | Path
        One golden JSON file, or a directory whose ``*.json`` files are read
        in sorted order.

    manifest_path : str | Path
        Corpus manifest used to bind positive spans to source files.

    Returns
    -------
    list[GoldenCase]
        Every case from every file, fully validated.

    Raises
    ------
    GoldenDataError
        If parsing, the cross-case uniqueness batch, or source verification
        rejects the data.

    Notes
    -----
    Validation runs cheapest-first: strict parsing, then cross-case
    uniqueness, then source I/O and hashing.
    """
    cases: list[GoldenCase] = []
    for golden_path in _golden_files(Path(path)):
        payload = _read_json(golden_path)
        if not isinstance(payload, list):
            raise GoldenDataError(f"golden file root must be a JSON array: {golden_path}")
        try:
            cases.extend(GOLDEN_CASES.validate_python(payload))
        except ValidationError as exc:
            raise GoldenDataError(f"invalid golden cases in {golden_path}: {exc}") from exc

    _validate_unique_cases(cases)
    validate_golden_sources(cases, manifest_path)
    return cases
