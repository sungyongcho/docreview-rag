"""Pure helpers of the readiness measurement script; no network."""

from scripts.diagnostics.readiness import Sample, percentile, phase_of, render_markdown, summarize


def test_percentile_uses_nearest_rank_and_tolerates_empty_input():
    """p50 and p95 pick actual observed values; an empty list yields zero."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert percentile(values, 0.5) == 50.0
    assert percentile(values, 0.95) == 100.0
    assert percentile([], 0.5) == 0.0


def test_phase_tags_follow_the_queued_job_status():
    """Samples are `before` until a job exists, `during` while it runs, `after` once terminal."""
    assert phase_of({"jobs": []}, None) == ("before", "-")
    running = {"jobs": [{"job_id": "j1", "status": "running", "stage": "parse"}]}
    assert phase_of(running, "j1") == ("during", "parse")
    finished = {"jobs": [{"job_id": "j1", "status": "succeeded", "stage": "done"}]}
    assert phase_of(finished, "j1") == ("after", "-")
    assert phase_of({"jobs": []}, "j1") == ("before", "-")


def test_summary_groups_by_endpoint_phase_and_stage_and_counts_failures():
    """Failures are counted but excluded from the latency percentiles."""
    samples = [
        Sample("/ready", 0.0, 100.0, True, "before", "-"),
        Sample("/ready", 0.5, 300.0, True, "before", "-"),
        Sample("/ready", 1.0, 5000.0, False, "during", "bm25"),
        Sample("/ready", 1.5, 900.0, True, "during", "bm25"),
        Sample("/health", 0.0, 5.0, True, "before", "-"),
    ]
    summary = summarize(samples)
    before = summary["/ready"]["before"]["-"]
    assert before == {"count": 2, "failures": 0, "p50_ms": 100.0, "p95_ms": 300.0, "max_ms": 300.0}
    during = summary["/ready"]["during"]["bm25"]
    assert during == {"count": 2, "failures": 1, "p50_ms": 900.0, "p95_ms": 900.0, "max_ms": 900.0}
    assert summary["/health"]["before"]["-"]["count"] == 1
    table = render_markdown(summary)
    assert table.splitlines()[0].startswith("| endpoint |")
    assert "| /ready | during | bm25 | 2 | 1 |" in table
