"""Benchmark independent parsing against the M3 parse-once corpus path.

Every timed measurement runs in a fresh interpreter, builds isolated temporary
PostgreSQL corpora, and reports semantic batch hashes alongside time and peak RSS.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import resource
from statistics import median
import subprocess
import sys
from time import perf_counter
from typing import Any, Literal

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.evals.retrieval_eval import (
    build_chunking_batch,
    load_chunking_filings,
    temporary_corpus_session,
)
from app.ingestion.seed import SeedBatch
from app.retrieval.embeddings import get_embedding_provider

type BenchmarkMode = Literal["baseline", "candidate"]

TARGETS = (500, 1200)


def _batch_digest(batch: SeedBatch) -> str:
    """Return a stable digest of every dataclass field in one seed batch."""
    payload = json.dumps(
        asdict(batch),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _profile_digests() -> dict[str, str]:
    """Return content hashes for parser profiles that a benchmark must not change.

    Returns
    -------
    dict[str, str]
        Profile paths mapped to SHA-256 digests in deterministic path order.
    """
    root = Path("data/profiles")
    return {
        path.as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.glob("*.json"))
    }


async def _measure_worker(mode: BenchmarkMode) -> dict[str, Any]:
    """Measure one fresh-process two-target indexing run.

    Parameters
    ----------
    mode : BenchmarkMode
        Independent parsing baseline or parse-once candidate path.

    Returns
    -------
    dict[str, Any]
        Per-target batch identities, phase durations, peak RSS, and profile integrity.

    Notes
    -----
    Each target owns a dedicated temporary PostgreSQL connection. Closing the context
    discards all indexed rows, and parser profile hashes must remain unchanged.
    """
    settings = get_settings().model_copy(update={"embedding_provider": "deterministic"})
    provider = get_embedding_provider(settings)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    profiles_before = _profile_digests()
    parsed_filings = None
    shared_parse_seconds = 0.0
    if mode == "candidate":
        started = perf_counter()
        parsed_filings = load_chunking_filings(settings=settings)
        shared_parse_seconds = perf_counter() - started

    targets: dict[str, dict[str, Any]] = {}
    batch_seconds = shared_parse_seconds
    target_work_seconds = 0.0
    try:
        for target in TARGETS:
            started = perf_counter()
            batch = build_chunking_batch(
                target,
                parsed_filings=parsed_filings,
                settings=settings,
            )
            target_batch_seconds = perf_counter() - started
            batch_seconds += target_batch_seconds
            digest = _batch_digest(batch)

            async with temporary_corpus_session(
                engine,
                batch,
                provider,
                target_text_chars=target,
                embedding_provider="deterministic",
            ) as (_session, measurement):
                database_seconds = measurement.target_phase_seconds

            target_total_seconds = target_batch_seconds + database_seconds
            target_work_seconds += target_total_seconds
            targets[str(target)] = {
                "batch_sha256": digest,
                "documents": len(batch.documents),
                "chunks": len(batch.chunks),
                "batch_seconds": target_batch_seconds,
                "database_seconds": database_seconds,
                "target_total_seconds": target_total_seconds,
            }
    finally:
        await engine.dispose()

    profiles_after = _profile_digests()
    return {
        "mode": mode,
        "targets": targets,
        "shared_parse_seconds": shared_parse_seconds,
        "batch_seconds": batch_seconds,
        "total_indexing_seconds": shared_parse_seconds + target_work_seconds,
        "max_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "profiles_unchanged": profiles_before == profiles_after,
    }


def _run_worker(mode: BenchmarkMode) -> dict[str, Any]:
    """Launch one isolated interpreter and decode its measurement.

    Parameters
    ----------
    mode : BenchmarkMode
        Worker path to execute in a fresh interpreter.

    Returns
    -------
    dict[str, Any]
        JSON measurement emitted by the worker process.

    Raises
    ------
    subprocess.CalledProcessError
        If the worker exits unsuccessfully.
    json.JSONDecodeError
        If the worker does not emit one valid JSON document.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.benchmark_m3_parse_once", "--worker", mode],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _semantic_signature(result: dict[str, Any]) -> dict[str, tuple[str, int, int]]:
    """Return the non-timing batch contract compared across paired runs."""
    return {
        target: (
            values["batch_sha256"],
            values["documents"],
            values["chunks"],
        )
        for target, values in result["targets"].items()
    }


def _summary(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate the predeclared parse-once acceptance gates.

    Parameters
    ----------
    pairs : list[dict[str, Any]]
        Completed paired baseline and candidate measurements.

    Returns
    -------
    dict[str, Any]
        Medians, improvements, memory change, individual gates, and final decision.

    Notes
    -----
    The default five-pair run requires at least four candidate wins, exact semantic
    equality, both time thresholds, the batch threshold, and the RSS ceiling.
    """
    baselines = [pair["baseline"] for pair in pairs]
    candidates = [pair["candidate"] for pair in pairs]
    baseline_total = median(item["total_indexing_seconds"] for item in baselines)
    candidate_total = median(item["total_indexing_seconds"] for item in candidates)
    absolute_improvement = baseline_total - candidate_total
    percent_improvement = absolute_improvement / baseline_total * 100
    baseline_batch = median(item["batch_seconds"] for item in baselines)
    candidate_batch = median(item["batch_seconds"] for item in candidates)
    batch_percent_improvement = (baseline_batch - candidate_batch) / baseline_batch * 100
    baseline_rss = median(item["max_rss_mib"] for item in baselines)
    candidate_rss = median(item["max_rss_mib"] for item in candidates)
    semantic_equivalence = all(
        _semantic_signature(pair["baseline"]) == _semantic_signature(pair["candidate"])
        and pair["baseline"]["profiles_unchanged"]
        and pair["candidate"]["profiles_unchanged"]
        for pair in pairs
    )
    wins = sum(
        candidate["total_indexing_seconds"] < baseline["total_indexing_seconds"]
        for baseline, candidate in zip(baselines, candidates, strict=True)
    )
    gates = {
        "semantic_equivalence": semantic_equivalence,
        "wins_at_least_4_of_5": wins >= 4,
        "total_improvement_at_least_10_percent": percent_improvement >= 10,
        "total_improvement_at_least_10_seconds": absolute_improvement >= 10,
        "batch_improvement_at_least_25_percent": batch_percent_improvement >= 25,
        "rss_within_110_percent": candidate_rss <= baseline_rss * 1.10,
    }
    return {
        "trials": len(pairs),
        "wins": wins,
        "baseline_median_total_seconds": baseline_total,
        "candidate_median_total_seconds": candidate_total,
        "absolute_improvement_seconds": absolute_improvement,
        "percent_improvement": percent_improvement,
        "baseline_median_batch_seconds": baseline_batch,
        "candidate_median_batch_seconds": candidate_batch,
        "batch_percent_improvement": batch_percent_improvement,
        "baseline_median_max_rss_mib": baseline_rss,
        "candidate_median_max_rss_mib": candidate_rss,
        "rss_percent_change": (candidate_rss - baseline_rss) / baseline_rss * 100,
        "gates": gates,
        "accepted": all(gates.values()),
    }


def _driver(trials: int, output: Path) -> int:
    """Run warmups and alternating AB/BA trial pairs, then write one JSON report.

    Parameters
    ----------
    trials : int
        Positive number of paired measurements after one warmup per mode.
    output : Path
        Destination for the complete benchmark report.

    Returns
    -------
    int
        Zero when semantic equivalence holds, otherwise one.

    Raises
    ------
    ValueError
        If ``trials`` is not positive.
    subprocess.CalledProcessError
        If any isolated worker fails.

    Notes
    -----
    Pair order alternates between AB and BA so cache and database warm-state effects
    are not assigned consistently to one implementation.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    print("warmup baseline", flush=True)
    _run_worker("baseline")
    print("warmup candidate", flush=True)
    _run_worker("candidate")

    pairs: list[dict[str, Any]] = []
    for index in range(trials):
        order: tuple[BenchmarkMode, BenchmarkMode] = (
            ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
        )
        pair: dict[str, Any] = {"pair": index + 1, "order": list(order)}
        for mode in order:
            print(f"pair {index + 1}/{trials} {mode}", flush=True)
            pair[mode] = _run_worker(mode)
        pairs.append(pair)

    report = {
        "benchmark": "m3-parse-once-two-target-indexing",
        "targets": list(TARGETS),
        "provider": "deterministic",
        "warmups_per_mode": 1,
        "pairs": pairs,
        "summary": _summary(pairs),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True), flush=True)
    if not report["summary"]["gates"]["semantic_equivalence"]:
        return 1
    return 0


def arguments() -> argparse.Namespace:
    """Parse benchmark driver and private worker arguments.

    Returns
    -------
    argparse.Namespace
        Trial count, optional output path, and hidden worker mode.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=("baseline", "candidate"), help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    """Run one private worker or the public paired benchmark driver.

    Returns
    -------
    int
        Process exit status from the selected worker or benchmark path.

    Raises
    ------
    SystemExit
        If driver mode is selected without the required output path.
    """
    args = arguments()
    if args.worker is not None:
        print(json.dumps(asyncio.run(_measure_worker(args.worker)), sort_keys=True))
        return 0
    if args.output is None:
        raise SystemExit("--output is required")
    return _driver(args.trials, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
