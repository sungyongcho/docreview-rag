"""Versioned job-wide progress stored beside the existing operation result references."""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.ingestion.progress import OperationProgress

PROGRESS_KEY = "operation_progress_v1"
# Equal stage weights express completion units, not estimated time remaining.
_PHASES = {
    "ingest_manifest": (("prepare",), ("schema",), ("documents",), ("chunks",), ("cleanup",)),
    "acquire_edgar": (("discover",), ("download",)),
    # DART selects and downloads each filing in turn; both share one filing counter.
    "acquire_dart": (("issuer_index",), ("select", "download")),
    "backfill_embeddings": (("embedding",),),
    "rebuild_bm25": (("bm25",),),
}


@dataclass(frozen=True, slots=True)
class JobProgress:
    """Persist monotonic completion separately from the current stage and item counters."""

    overall_current: int
    overall_total: int
    stage_index: int
    stage_count: int
    stage_started_at: datetime
    progress_stage: str

    def references(self, refs: dict[str, object] | None) -> dict[str, object]:
        """Merge a JSON-safe snapshot without replacing usage or acquisition evidence."""
        payload = asdict(self)
        payload["stage_started_at"] = self.stage_started_at.isoformat()
        return {**(refs or {}), PROGRESS_KEY: payload}


def stored_progress(refs: dict[str, object] | None) -> JobProgress | None:
    """Read our versioned snapshot; legacy jobs have no measured overall progress."""
    raw = (refs or {}).get(PROGRESS_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        values = [
            raw[name] for name in ("overall_current", "overall_total", "stage_index", "stage_count")
        ]
        if any(type(value) is not int for value in values):
            return None
        current, total, index, count = values
        if not (0 <= current <= total == 100 and 1 <= index <= count):
            return None
        timestamp = datetime.fromisoformat(raw["stage_started_at"])
        if timestamp.tzinfo is None or not isinstance(raw["progress_stage"], str):
            return None
        return JobProgress(current, total, index, count, timestamp, raw["progress_stage"])
    except KeyError, TypeError, ValueError:
        return None


def progress_fields(refs: dict[str, object]) -> dict[str, Any]:
    """Project stored progress into the typed API without inventing legacy counters."""
    progress = stored_progress(refs)
    return asdict(progress) if progress is not None else {}


def advance_progress(
    kind: str,
    refs: dict[str, object] | None,
    progress: OperationProgress,
    now: datetime,
) -> dict[str, object]:
    """Advance stage-weighted units, reserving the final unit for successful completion."""
    phases = _PHASES.get(kind)
    if phases is None:
        return dict(refs or {})
    index = next((i for i, names in enumerate(phases) if progress.stage in names), None)
    if index is None:
        return dict(refs or {})
    previous = stored_progress(refs)
    # Only acquisition detail counters represent bytes in the current unfinished item.
    item_fraction = 0.0
    if (
        kind in {"acquire_edgar", "acquire_dart"}
        and progress.stage in {"issuer_index", "download"}
        and progress.detail_current is not None
        and progress.detail_total is not None
        and progress.detail_total > 0
    ):
        item_fraction = min(max(progress.detail_current / progress.detail_total, 0), 1)
    fraction = (
        min(max((progress.current + item_fraction) / progress.total, 0), 1)
        if progress.total is not None and progress.total > 0
        else item_fraction
        if progress.stage == "issuer_index"
        else 0
    )
    overall = min(99, int(99 * (index + fraction) / len(phases)))
    if previous is not None:
        overall = max(previous.overall_current, overall)
    started = (
        previous.stage_started_at
        if previous is not None and previous.progress_stage == progress.stage
        else now
    )
    return JobProgress(overall, 100, index + 1, len(phases), started, progress.stage).references(
        refs
    )


def start_progress(kind: str, refs: dict[str, object] | None, now: datetime) -> dict[str, object]:
    """Start a known job at zero before its first potentially slow stage callback."""
    phases = _PHASES.get(kind)
    if phases is None:
        return dict(refs or {})
    return advance_progress(kind, refs, OperationProgress(phases[0][0], 0, None, "Starting"), now)


def finish_progress(refs: dict[str, object] | None) -> dict[str, object]:
    """Mark successful completion while retaining the last real stage for history."""
    previous = stored_progress(refs)
    if previous is None:
        return dict(refs or {})
    return JobProgress(
        100,
        100,
        previous.stage_count,
        previous.stage_count,
        previous.stage_started_at,
        previous.progress_stage,
    ).references(refs)
