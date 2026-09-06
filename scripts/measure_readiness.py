"""Measure ``/health`` and ``/ready`` latency, optionally around one ingest job.

The script samples both endpoints on a fixed interval and tags every sample with the
job phase (``before`` / ``during`` / ``after``) and the running job's stage read from
``/admin/jobs``. ``/health`` performs no database work, so its latency isolates event
loop stalls; the gap between ``/ready`` and ``/health`` is the readiness probe's own
cost. Point it at an isolated stack: with ``--ingest`` it queues a real corpus job.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import sys
import time
from typing import Any

import httpx

ENDPOINTS: tuple[str, ...] = ("/health", "/ready")
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


@dataclass(frozen=True, slots=True)
class Sample:
    """One timed request against one endpoint."""

    endpoint: str
    offset_s: float
    latency_ms: float
    ok: bool
    phase: str
    stage: str


def percentile(values: list[float], fraction: float) -> float:
    """Return the nearest-rank percentile of ``values`` (``fraction`` in ``[0, 1]``)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, int(round(fraction * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]


def phase_of(board: dict[str, Any], job_id: str | None) -> tuple[str, str]:
    """Return the ``(phase, stage)`` tag for one board reading relative to ``job_id``."""
    if job_id is None:
        return "before", "-"
    for job in board.get("jobs", ()):
        if job.get("job_id") != job_id:
            continue
        status = str(job.get("status", ""))
        if status in TERMINAL_STATUSES:
            return "after", "-"
        return "during", str(job.get("stage") or "-")
    return "before", "-"


def summarize(samples: list[Sample]) -> dict[str, dict[str, dict[str, dict[str, float | int]]]]:
    """Aggregate samples by endpoint, phase and stage into count and latency figures."""
    groups: dict[tuple[str, str, str], list[Sample]] = {}
    for sample in samples:
        groups.setdefault((sample.endpoint, sample.phase, sample.stage), []).append(sample)
    summary: dict[str, dict[str, dict[str, dict[str, float | int]]]] = {}
    for (endpoint, phase, stage), rows in sorted(groups.items()):
        latencies = [row.latency_ms for row in rows if row.ok]
        summary.setdefault(endpoint, {}).setdefault(phase, {})[stage] = {
            "count": len(rows),
            "failures": sum(1 for row in rows if not row.ok),
            "p50_ms": round(percentile(latencies, 0.5), 1),
            "p95_ms": round(percentile(latencies, 0.95), 1),
            "max_ms": round(max(latencies), 1) if latencies else 0.0,
        }
    return summary


def render_markdown(summary: dict[str, dict[str, dict[str, dict[str, float | int]]]]) -> str:
    """Render the summary as one Markdown table for a pull request."""
    lines = [
        "| endpoint | phase | stage | count | failures | p50 ms | p95 ms | max ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for endpoint, phases in summary.items():
        for phase, stages in phases.items():
            for stage, row in stages.items():
                lines.append(
                    f"| {endpoint} | {phase} | {stage} | {row['count']} | {row['failures']} "
                    f"| {row['p50_ms']} | {row['p95_ms']} | {row['max_ms']} |"
                )
    return "\n".join(lines)


async def _timed_get(client: httpx.AsyncClient, path: str) -> tuple[float, bool]:
    """Return ``(latency_ms, ok)`` for one request; any exception counts as a failure."""
    started = time.perf_counter()
    try:
        response = await client.get(path)
        ok = response.status_code < 500 or path == "/ready"
    except httpx.HTTPError:
        ok = False
    return (time.perf_counter() - started) * 1000.0, ok


async def _board(client: httpx.AsyncClient) -> dict[str, Any]:
    """Read the operator job board, treating any failure as an empty board."""
    try:
        response = await client.get("/admin/jobs")
        if response.status_code == 200:
            return response.json()
    except httpx.HTTPError:
        pass
    return {"jobs": []}


async def measure(
    base_url: str,
    *,
    seconds: float,
    interval: float,
    timeout: float,
    ingest: dict[str, Any] | None,
    warmup: float,
    cooldown: float,
) -> dict[str, Any]:
    """Sample the endpoints for ``seconds`` (or around one queued ingest job) and summarize."""
    samples: list[Sample] = []
    job_id: str | None = None
    job_record: dict[str, Any] | None = None
    started = time.perf_counter()
    terminal_at: float | None = None
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        while True:
            offset = time.perf_counter() - started
            if ingest is not None and job_id is None and offset >= warmup:
                response = await client.post("/admin/corpus/jobs", json=ingest)
                response.raise_for_status()
                created = response.json()
                job_id = str(created["job_id"])
                job_record = created
            board = await _board(client)
            phase, stage = phase_of(board, job_id)
            if job_id is not None:
                for job in board.get("jobs", ()):
                    if job.get("job_id") == job_id:
                        job_record = job
            for endpoint in ENDPOINTS:
                latency, ok = await _timed_get(client, endpoint)
                samples.append(
                    Sample(endpoint, round(offset, 3), round(latency, 3), ok, phase, stage)
                )
            if phase == "after" and terminal_at is None:
                terminal_at = offset
            if ingest is None:
                done = offset >= seconds
            else:
                done = terminal_at is not None and offset - terminal_at >= cooldown
            if done:
                break
            await asyncio.sleep(interval)
    return {
        "base_url": base_url,
        "interval_s": interval,
        "timeout_s": timeout,
        "samples": len(samples),
        "job": job_record,
        "summary": summarize(samples),
    }


def main() -> int:
    """Run the measurement from the command line and print JSON (plus Markdown on request)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001", help="API origin, no proxy")
    parser.add_argument("--seconds", type=float, default=30.0, help="window without --ingest")
    parser.add_argument("--interval", type=float, default=0.5, help="seconds between rounds")
    parser.add_argument("--timeout", type=float, default=5.0, help="per-request timeout (web: 5 s)")
    parser.add_argument("--ingest", metavar="SELECTION_ID", help="queue one ingest_manifest job")
    parser.add_argument("--manifest", default="manifest.json", help="manifest path in the corpus")
    parser.add_argument("--warmup", type=float, default=10.0, help="seconds sampled before the job")
    parser.add_argument("--cooldown", type=float, default=10.0, help="seconds sampled after it")
    parser.add_argument("--markdown", action="store_true", help="also print a Markdown table")
    args = parser.parse_args()
    ingest = None
    if args.ingest:
        ingest = {"kind": "ingest_manifest", "manifest": args.manifest, "selection_id": args.ingest}
    result = asyncio.run(
        measure(
            args.base_url,
            seconds=args.seconds,
            interval=args.interval,
            timeout=args.timeout,
            ingest=ingest,
            warmup=args.warmup,
            cooldown=args.cooldown,
        )
    )
    print(json.dumps(result, indent=2))
    if args.markdown:
        print(render_markdown(result["summary"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
