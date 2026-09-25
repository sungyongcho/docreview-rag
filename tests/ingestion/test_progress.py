"""Progress display wiring: what the hooks do to a bar, not how a bar renders."""

import pytest

import app.ingestion.progress as progress
from app.ingestion.progress import OperationProgress, operation_bar


class FakeBar:
    """Stand-in for one tqdm instance, recording what the hooks do to it."""

    def __init__(self, **options) -> None:
        self.options = options
        self.desc = options.get("desc")
        self.total = options.get("total")
        self.n = 0
        self.postfix: str | None = None
        self.refreshes = 0
        self.resets: list[int | None] = []
        self.closed = False

    def __enter__(self) -> FakeBar:
        return self

    def __exit__(self, *exception: object) -> bool:
        self.closed = True
        return False

    def refresh(self) -> None:
        """Record one redraw."""
        self.refreshes += 1

    def reset(self, *, total: int | None = None) -> None:
        """Reset the recorded count and timing boundary for a new stage."""
        self.n = 0
        self.total = total
        self.resets.append(total)

    def set_description_str(self, text: str) -> None:
        """Record the active operation stage."""
        self.desc = text

    def set_postfix_str(self, text: str) -> None:
        """Record the latest position label."""
        self.postfix = text


@pytest.fixture
def bars(monkeypatch) -> list[FakeBar]:
    """Replace tqdm with a recorder and collect every bar the module opens."""
    opened: list[FakeBar] = []

    def factory(**options) -> FakeBar:
        """Create and record a fake tqdm bar."""
        bar = FakeBar(**options)
        opened.append(bar)
        return bar

    monkeypatch.setattr(progress, "tqdm", factory)
    return opened


def test_operation_bar_tracks_absolute_multi_stage_updates(bars):
    """One terminal bar follows stage resets without accumulating old counts."""
    with operation_bar("Ingest", unit="batch") as report:
        report(OperationProgress("parse", 2, 5, "NVDA FY2024"))
        report(OperationProgress("persist", 1, 3, "500 chunks"))

    bar = bars[0]
    assert bar.options["unit"] == "batch"
    assert bar.desc == "Ingest · persist"
    assert (bar.n, bar.total) == (1, 3)
    assert bar.postfix == "500 chunks"
    assert bar.refreshes == 2
    assert bar.resets == [5, 3]
    assert bar.closed
