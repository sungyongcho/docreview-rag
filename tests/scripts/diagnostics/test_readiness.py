"""Readiness diagnostics against deterministic local HTTP responses; no network."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from scripts.diagnostics.readiness import Sample, render_markdown, summarize


def test_summary_groups_by_endpoint_phase_and_stage_and_counts_failures():
    """Failures are counted but excluded from the latency percentiles."""
    samples = [
        Sample("/ready", 0.0, 100.0, True, "before", "-"),
        Sample("/ready", 0.5, 300.0, True, "before", "-"),
        Sample("/ready", 1.0, 5000.0, False, "during", "bm25"),
        Sample("/ready", 1.5, 900.0, True, "during", "bm25"),
        Sample("/health", 0.0, 5.0, True, "before", "-"),
    ]
    samples.extend(Sample("/health", i, float(i + 1), True, "after", "-") for i in range(11))
    summary = summarize(samples)
    before = summary["/ready"]["before"]["-"]
    assert before == {"count": 2, "failures": 0, "p50_ms": 100.0, "p95_ms": 300.0, "max_ms": 300.0}
    during = summary["/ready"]["during"]["bm25"]
    assert during == {"count": 2, "failures": 1, "p50_ms": 900.0, "p95_ms": 900.0, "max_ms": 900.0}
    assert summary["/health"]["before"]["-"]["count"] == 1
    assert summary["/health"]["after"]["-"]["p95_ms"] == 11
    table = render_markdown(summary)
    assert table.splitlines()[0].startswith("| endpoint |")
    assert "| /ready | during | bm25 | 2 | 1 |" in table


def test_ingest_measurement_reports_job_lookup_failures(monkeypatch):
    """A failed job read must abort instead of becoming an empty, apparently idle board."""
    from scripts.diagnostics import readiness

    job_reads = 0

    def respond(request):
        """Fail the first job read, then expose a terminal record to bound the old loop."""
        nonlocal job_reads
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "j1", "status": "queued"})
        if request.url.path.startswith("/admin/jobs"):
            job_reads += 1
            if job_reads == 1:
                return httpx.Response(503, json={"detail": "database unavailable"})
            return httpx.Response(200, json={"jobs": [{"job_id": "j1", "status": "succeeded"}]})
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(readiness.httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(httpx.HTTPStatusError, match="503"):
        asyncio.run(
            readiness.measure(
                "http://test",
                seconds=1,
                interval=0,
                timeout=1,
                ingest={"kind": "ingest_manifest", "selection_id": "sample"},
                warmup=0,
                cooldown=0,
            )
        )


@pytest.mark.parametrize("ingest", [None, {"kind": "ingest_manifest", "selection_id": "sample"}])
def test_measurement_tracks_one_job_and_counts_real_endpoint_failures(monkeypatch, ingest):
    """Standalone sampling needs no admin access; ingestion follows its persisted job only."""
    from scripts.diagnostics import readiness

    offsets = iter(range(30))
    monkeypatch.setattr(readiness, "time", SimpleNamespace(perf_counter=lambda: next(offsets)))
    job_reads = 0
    phases = iter(("queued", "running", "succeeded"))

    def respond(request):
        """Expose a queue lifecycle and distinguish degraded readiness from server errors."""
        nonlocal job_reads
        if request.method == "POST":
            assert request.url.path == "/admin/corpus/jobs"
            return httpx.Response(202, json={"job_id": "j1", "status": "queued"})
        if request.url.path == "/admin/jobs/j1":
            assert ingest is not None
            job_reads += 1
            return httpx.Response(
                200, json={"job_id": "j1", "status": next(phases), "stage": "parse"}
            )
        if request.url.path == "/health":
            return httpx.Response(500)
        assert request.url.path == "/ready"
        return httpx.Response(500 if job_reads == 2 else 503)

    client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(readiness.httpx, "AsyncClient", lambda **kwargs: client)
    result = asyncio.run(
        readiness.measure(
            "http://test",
            seconds=0,
            interval=0,
            timeout=1,
            ingest=ingest,
            warmup=2,
            cooldown=0,
        )
    )
    summary = result["summary"]
    assert summary["/health"]["before"]["-"]["failures"] == 1
    assert summary["/ready"]["before"]["-"]["failures"] == 0
    if ingest is None:
        assert result["job"] is None
        assert result["samples"] == 2
    else:
        assert result["job"]["status"] == "succeeded"
        assert result["samples"] == 8
        assert summary["/ready"]["during"]["parse"]["count"] == 2
        assert summary["/ready"]["during"]["parse"]["failures"] == 1
        assert summary["/ready"]["after"]["-"]["failures"] == 0
