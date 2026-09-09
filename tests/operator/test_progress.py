"""Job-wide progress across corpus stages and persisted API projections."""

from datetime import UTC, datetime, timedelta

import pytest

from app.ingestion.progress import OperationProgress
from app.operator.progress import (
    advance_progress,
    finish_progress,
    progress_fields,
    start_progress,
    stored_progress,
)


def test_ingest_progress_never_resets_and_finishes_only_after_success():
    """Keep the current stage independent from monotonic overall completion."""
    now = datetime.now(UTC)
    refs = start_progress("ingest_manifest", {"retry_of": "earlier"}, now)
    values = [0]
    for index, stage in enumerate(("prepare", "schema", "documents", "chunks", "cleanup")):
        for current in (0, 1, 2):
            stamp = now + timedelta(seconds=index * 10 + current)
            refs = advance_progress(
                "ingest_manifest", refs, OperationProgress(stage, current, 2, stage), stamp
            )
            state = stored_progress(refs)
            assert state is not None
            values.append(state.overall_current)
            assert state.stage_index == index + 1
            assert state.stage_started_at == now + timedelta(seconds=index * 10)
    assert values == sorted(values)
    assert max(values) == 99
    assert refs["retry_of"] == "earlier"
    completed = progress_fields(finish_progress(refs))
    assert completed["overall_current"] == 100
    assert completed["progress_stage"] == "cleanup"
    assert completed["stage_index"] == completed["stage_count"] == 5


def test_dart_interleaved_select_download_counts_filings_once():
    """Do not jump to completion after the first filing's download or regress at select."""
    now = datetime.now(UTC)
    refs = start_progress("acquire_dart", {}, now)
    values = []
    for stage, current in (("select", 0), ("download", 1), ("select", 1), ("download", 2)):
        refs = advance_progress("acquire_dart", refs, OperationProgress(stage, current, 2, ""), now)
        state = stored_progress(refs)
        assert state is not None
        values.append(state.overall_current)
    assert values == [49, 74, 74, 99]


@pytest.mark.parametrize(
    "kind,stage", [("backfill_embeddings", "embedding"), ("rebuild_bm25", "bm25")]
)
def test_single_stage_progress_reserves_terminal_completion(kind, stage):
    """A finished last batch remains below 100 until the operation's postconditions pass."""
    refs = advance_progress(kind, {}, OperationProgress(stage, 1, 1, "done"), datetime.now(UTC))
    assert progress_fields(refs)["overall_current"] == 99
    assert progress_fields(finish_progress(refs))["overall_current"] == 100


def test_legacy_and_invalid_progress_do_not_invent_overall_values():
    """Keep old or malformed ledger metadata nullable instead of manufacturing percentages."""
    assert progress_fields({}) == {}
    assert progress_fields({"operation_progress_v1": {"overall_current": "100"}}) == {}


@pytest.mark.parametrize(
    "kind,stage,current,total,read,length,expected",
    [
        ("acquire_dart", "issuer_index", 0, None, 475136, 3603839, 6),
        ("acquire_dart", "issuer_index", 0, None, 3603839, 3603839, 49),
        ("acquire_dart", "download", 1, 2, 500, 1000, 86),
        ("acquire_edgar", "download", 0, 2, 500, 1000, 61),
        ("acquire_edgar", "download", 1, 2, 1500, 1000, 99),
        ("acquire_dart", "issuer_index", 0, None, 500, None, 0),
        ("acquire_dart", "issuer_index", 0, None, 500, 0, 0),
        ("ingest_manifest", "documents", 0, 2, 500, 1000, 39),
    ],
)
def test_download_bytes_contribute_only_to_acquisition_progress(
    kind, stage, current, total, read, length, expected
):
    """Combine completed items and known byte fractions without guessing unknown lengths."""
    refs = advance_progress(
        kind, {}, OperationProgress(stage, current, total, "", read, length), datetime.now(UTC)
    )
    assert progress_fields(refs)["overall_current"] == expected


def test_download_retry_and_item_transition_preserve_overall_progress():
    """A byte counter reset never rolls back completion or counts an item twice."""
    refs = {}
    values = []
    for current, read, length in [(0, 800, 1000), (0, 0, 1000), (1, None, None), (1, 500, 1000)]:
        refs = advance_progress(
            "acquire_edgar",
            refs,
            OperationProgress("download", current, 2, "", read, length),
            datetime.now(UTC),
        )
        values.append(progress_fields(refs)["overall_current"])
    assert values == [69, 69, 74, 86]
