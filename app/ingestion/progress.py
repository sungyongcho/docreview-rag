"""Progress hooks shared by long-running corpus operations.

A corpus build waits on two very different clocks: how many filings are left, and
how far the current multi-megabyte body has come. ``OperationProgress`` carries both
in one transport-neutral update — a stage position plus optional byte detail — so an
administrative job and a terminal bar read the same events. DART spends minutes
inside a single response, so a display that ticks once per filing would look hung.

Nothing here decides what to fetch. The acquisition modules take a ``ByteProgress``
hook and call it as bytes arrive; their callers bridge that hook onto operation
updates, which keeps ``tqdm`` out of the fetch contracts entirely. ``operation_bar``
is the one place that draws those updates as a bar.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from tqdm import tqdm

# Absolute bytes read so far, and the length the response declared when it declared
# one. Absolute rather than incremental so a retried request can restart its own
# count without the display having to unwind anything.
ByteProgress = Callable[[int, int | None], None]


@dataclass(frozen=True, slots=True)
class OperationProgress:
    """One transport-neutral update for a long corpus operation."""

    stage: str
    current: int
    total: int | None
    message: str
    detail_current: int | None = None
    detail_total: int | None = None


OperationProgressCallback = Callable[[OperationProgress], None]


@contextmanager
def operation_bar(description: str, *, unit: str = "step") -> Iterator[OperationProgressCallback]:
    """Render absolute multi-stage operation updates on one reusable terminal bar."""
    with tqdm(total=None, unit=unit, desc=description, disable=None) as bar:
        active_stage: str | None = None

        def report(progress: OperationProgress) -> None:
            """Synchronize stage, total, position, and human-readable detail."""
            nonlocal active_stage
            if progress.stage != active_stage:
                active_stage = progress.stage
                bar.reset(total=progress.total)
                bar.set_description_str(f"{description} · {progress.stage}")
            elif bar.total != progress.total:
                bar.total = progress.total
            bar.n = progress.current
            bar.set_postfix_str(progress.message)
            bar.refresh()

        yield report


def byte_progress(
    publish: OperationProgressCallback | None, progress: OperationProgress
) -> ByteProgress | None:
    """Attach decoded byte counts to one operation's current filing or discovery step."""
    if publish is None:
        return None

    def report(read: int, total: int | None) -> None:
        """Publish the same operation position with updated stream detail."""
        publish(replace(progress, detail_current=read, detail_total=total))

    return report
