"""Load strict golden cases and bind every positive span to the raw corpus."""

from collections import defaultdict
from collections.abc import Iterable
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
from pydantic import TypeAdapter, ValidationError

from app.evals.golden.models import (
    GoldenCase,
    GoldenDataError,
    GoldenSpan,
    SourceMissingError,
    validate_unique_cases,
)
from app.evals.results.artifacts import read_strict_json
from app.ingestion.parsing.html import source_digest
from app.ingestion.sources.models import FilingSource, Manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "retrieval.json"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "corpus" / "manifest.json"
GOLDEN_CASES = TypeAdapter(list[GoldenCase])


def encode_golden_payload(payload: list[dict[str, object]]) -> bytes:
    """Encode one canonical human-reviewable golden JSON document."""
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()


def golden_payload_sha256(payload: list[dict[str, object]]) -> str:
    """Hash the canonical bytes used by DB revisions and temporary eval inputs."""
    return hashlib.sha256(encode_golden_payload(payload)).hexdigest()


def _manifest_sources(manifest_path: Path, selection_id: str) -> dict[str, FilingSource]:
    """Resolve only the exact primary artifacts selected by the common catalog."""
    try:
        manifest = Manifest.read(manifest_path)
        sources = manifest.selected_sources(selection_id, manifest_path.resolve().parent)
    except (OSError, ValueError) as exc:
        raise GoldenDataError(f"invalid corpus manifest: {exc}") from exc
    return {source.document.document_id: source for source in sources}


def validate_golden_sources(
    cases: Iterable[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    selection_id: str = "sec-evaluation",
    sources: dict[str, FilingSource] | None = None,
) -> None:
    """Verify each positive span against its exact selected source and SHA-256.

    Parameters
    ----------
    cases : Iterable[GoldenCase]
        Cases whose positive answer spans are checked against the corpus.

    manifest_path : str | Path
        Corpus manifest used to resolve each cited document id.
    selection_id : str
        Explicit named processing selection; defaults to the committed SEC suite.

    Raises
    ------
    GoldenDataError
        If a span cites an unknown document, its snapshot hash does not match,
        its interval leaves the document, or it contains no visible text.

    Notes
    -----
    Spans are grouped by cited document so each source is read, hashed, and
    checked once and then released; peak memory is one decoded filing rather
    than the whole cited corpus. Each artifact verifies its acquired bytes before
    decoding; golden hashes identify decoded text using the ingestion source digest.
    """
    sources = (
        sources if sources is not None else _manifest_sources(Path(manifest_path), selection_id)
    )
    cited: dict[str, list[tuple[str, GoldenSpan]]] = defaultdict(list)
    for case in cases:
        for answer in case.answers:
            cited[answer.doc_id].append((case.id, answer))

    for document_id, spans in cited.items():
        source_path = sources.get(document_id)
        if source_path is None:
            first_case_id = spans[0][0]
            raise GoldenDataError(f"{first_case_id} cites unknown corpus document {document_id}")
        try:
            raw_source = source_path.read()
        except FileNotFoundError as exc:
            raise SourceMissingError(f"missing verified source for {document_id}") from exc
        except (OSError, ValueError) as exc:
            raise GoldenDataError(f"cannot read verified source for {document_id}: {exc}") from exc
        digest = source_digest(raw_source)

        for case_id, answer in spans:
            if answer.source_sha256 != digest:
                raise GoldenDataError(f"{case_id} source hash does not match {document_id}")
            if answer.end_char > len(raw_source):
                raise GoldenDataError(
                    f"{case_id} span ends beyond {document_id}: "
                    f"{answer.end_char} > {len(raw_source)}"
                )
            evidence = BeautifulSoup(
                raw_source[answer.start_char : answer.end_char],
                "html.parser",
            ).get_text(" ", strip=True)
            if not evidence:
                raise GoldenDataError(
                    f"{case_id} span has no visible source evidence in {document_id}"
                )


def load_golden_cases(
    path: str | Path = DEFAULT_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    selection_id: str = "sec-evaluation",
) -> list[GoldenCase]:
    """Load one golden suite file and validate all of its source citations.

    Parameters
    ----------
    path : str | Path
        One golden JSON file holding a complete suite.

    manifest_path : str | Path
        Corpus manifest used to bind positive spans to source files.
    selection_id : str
        Explicit named processing selection; defaults to the committed SEC suite.

    Returns
    -------
    list[GoldenCase]
        Every case in the file, fully validated.

    Raises
    ------
    GoldenDataError
        If parsing, the cross-case uniqueness batch, or source verification
        rejects the data.

    Notes
    -----
    A suite is exactly one file. Translated twins such as ``retrieval_ko.json``
    reuse their English suite's case ids on purpose, so sibling files in one
    directory are separate suites and are never merged into a single load.
    The file root is either a plain case array or a ``docreview-golden-set``
    envelope whose ``cases`` member holds that array.
    Validation runs cheapest-first: strict parsing, then cross-case uniqueness,
    then source I/O and hashing.
    """
    golden_path = Path(path)
    payload = read_strict_json(golden_path, error=GoldenDataError)
    if isinstance(payload, dict) and payload.get("format") == "docreview-golden-set":
        payload = payload.get("cases")
    if not isinstance(payload, list):
        raise GoldenDataError(f"golden file root must be a JSON array: {golden_path}")
    try:
        cases = GOLDEN_CASES.validate_python(payload)
    except ValidationError as exc:
        raise GoldenDataError(f"invalid golden cases in {golden_path}: {exc}") from exc

    validate_unique_cases(cases)
    validate_golden_sources(cases, manifest_path, selection_id=selection_id)
    return cases
