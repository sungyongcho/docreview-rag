"""Built-in golden suite catalog and its source-readiness listing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Final, Literal

from app.evals.contracts import GoldenSuiteId, GoldenSuiteResource
from app.evals.golden.binding import bind_golden
from app.evals.golden.loading import GOLDEN_CASES
from app.evals.golden.models import GoldenDataError
from app.evals.results.artifacts import read_strict_json


@dataclass(frozen=True, slots=True)
class GoldenSuiteDefinition:
    """Filesystem and corpus-language binding for one public suite identity."""

    suite_id: GoldenSuiteId
    label: str
    title: str
    registry: Literal["sec", "dart"]
    question_language: Literal["en", "ko", "mixed"]
    corpus_language: Literal["en", "ko"]
    golden_name: str
    manifest_name: str


SUITES: Final[dict[GoldenSuiteId, GoldenSuiteDefinition]] = {
    "sec-en_v2_astra": GoldenSuiteDefinition(
        "sec-en_v2_astra",
        "SEC 10-K · English _v2_astra",
        "SEC · English v2",
        "sec",
        "en",
        "en",
        "sec_en_v2_astra.json",
        "manifest.json",
    ),
    "sec-ko_v2_astra": GoldenSuiteDefinition(
        "sec-ko_v2_astra",
        "SEC 10-K · Korean _v2_astra",
        "SEC · Korean v2",
        "sec",
        "ko",
        "en",
        "sec_ko_v2_astra.json",
        "manifest.json",
    ),
    "sec-mixed_v2_astra": GoldenSuiteDefinition(
        "sec-mixed_v2_astra",
        "SEC 10-K · Mixed EN/KO _v2_astra",
        "SEC · Mixed v2",
        "sec",
        "mixed",
        "en",
        "sec_mixed_v2_astra.json",
        "manifest.json",
    ),
    "sec-en": GoldenSuiteDefinition(
        "sec-en",
        "SEC 10-K · English",
        "SEC retrieval",
        "sec",
        "en",
        "en",
        "retrieval.json",
        "manifest.json",
    ),
    "sec-ko": GoldenSuiteDefinition(
        "sec-ko",
        "SEC 10-K · Korean questions",
        "SEC retrieval · Korean",
        "sec",
        "ko",
        "en",
        "retrieval_ko.json",
        "manifest.json",
    ),
    "dart-en": GoldenSuiteDefinition(
        "dart-en",
        "DART · English questions",
        "DART retrieval",
        "dart",
        "en",
        "ko",
        "dart_retrieval.json",
        "manifest.json",
    ),
    "dart-ko": GoldenSuiteDefinition(
        "dart-ko",
        "DART · Korean",
        "DART retrieval · Korean",
        "dart",
        "ko",
        "ko",
        "dart_retrieval_ko.json",
        "manifest.json",
    ),
}


def suite_paths(
    suite_id: GoldenSuiteId, *, golden_dir: Path, corpus_dir: Path
) -> tuple[Path, Path]:
    """Return golden and corpus manifest paths for one suite."""
    definition = SUITES[suite_id]
    return (
        golden_dir / definition.golden_name,
        corpus_dir / definition.manifest_name,
    )


def golden_file_sha256(path: Path) -> str:
    """Hash the exact golden JSON bytes used by a run."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def suite_resources(golden_dir: Path, corpus_dir: Path) -> tuple[GoldenSuiteResource, ...]:
    """Inspect all suite contracts while reporting missing source readiness safely."""
    resources: list[GoldenSuiteResource] = []
    for definition in SUITES.values():
        golden_path, manifest_path = suite_paths(
            definition.suite_id, golden_dir=golden_dir, corpus_dir=corpus_dir
        )
        payload = read_strict_json(golden_path, error=GoldenDataError)
        cases = GOLDEN_CASES.validate_python(payload)
        source_ready = True
        source_error = None
        source_error_code = None
        checks = ()
        try:
            bound = await asyncio.to_thread(
                bind_golden, payload, manifest_path, definition.registry
            )
            checks = bound.sources
            source_ready = bound.ready
            failed = [source for source in checks if source.state != "ready"]
            if failed:
                source_error_code = (
                    "source_invalid"
                    if any(source.state == "source_invalid" for source in failed)
                    else "source_missing"
                )
                source_error = "; ".join(
                    f"{source.issuer} FY{source.fiscal_year}: {source.detail}" for source in failed
                )
        except (GoldenDataError, OSError, ValueError) as error:
            source_ready = False
            source_error = str(error)
            source_error_code = "source_invalid"
        positive = sum(bool(case.answers) for case in cases)
        resources.append(
            GoldenSuiteResource(
                filename=golden_path.name,
                suite_id=definition.suite_id,
                label=definition.label,
                title=definition.title,
                registry=definition.registry,
                question_language=definition.question_language,
                corpus_language=definition.corpus_language,
                case_count=len(cases),
                scored_positive_cases=positive,
                absent_cases=len(cases) - positive,
                curation_status="agent-curated",
                approval_status="pending-author-approval",
                human_verified=False,
                golden_sha256=golden_file_sha256(golden_path),
                source_ready=source_ready,
                source_checks=checks,
                source_error=source_error,
                source_error_code=source_error_code,
            )
        )
    return tuple(resources)
