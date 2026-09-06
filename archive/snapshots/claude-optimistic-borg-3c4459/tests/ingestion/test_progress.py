"""Progress display wiring: what the hooks do to a bar, not how a bar renders."""

import pytest

import app.ingestion.progress as progress
from app.ingestion.progress import OperationProgress, byte_bar, operation_bar, overall_bar


class FakeBar:
    """Stand-in for one tqdm instance, recording what the hooks do to it."""

    def __init__(self, **options) -> None:
        self.options = options
        self.desc = options.get("desc")
        self.total = options.get("total")
        self.n = 0
        self.postfix: str | None = None
        self.lines: list[str] = []
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

    def update(self, count: int) -> None:
        """Advance the recorded item count."""
        self.n += count

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

    def write(self, line: str) -> None:
        """Record one line emitted above the bar."""
        self.lines.append(line)


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


def test_byte_bar_scales_bytes_and_clears_itself(bars):
    """A download bar is byte-scaled and leaves the screen to the result lines."""
    with byte_bar("NVDA FY2024") as report:
        report(0, 2048)
    bar = bars[0]

    assert bar.options["unit"] == "B"
    assert bar.options["unit_scale"] is True
    assert bar.options["leave"] is False
    assert bar.options["desc"] == "NVDA FY2024"
    assert bar.closed


def test_declared_length_becomes_the_total(bars):
    """A response that declares its length gets a bar with a destination."""
    with byte_bar("x") as report:
        report(0, 4096)
        report(1024, 4096)

    assert (bars[0].total, bars[0].n) == (4096, 1024)


def test_an_undeclared_length_leaves_the_bar_open_ended(bars):
    """Chunked responses still advance; only the percentage is unavailable."""
    with byte_bar("x") as report:
        report(1024, None)

    assert bars[0].total is None
    assert bars[0].n == 1024


def test_a_retry_rewinds_the_bar_instead_of_double_counting(bars):
    """The hook carries absolute bytes, so a restarted request restarts the count."""
    with byte_bar("x") as report:
        report(3000, 5000)
        report(0, 5000)
        report(500, 5000)

    assert bars[0].n == 500


def test_overall_bar_counts_items_and_labels_the_position(bars):
    """The outer bar advances per finished item and names where it is."""
    with overall_bar(3, unit="doc", description="EDGAR") as overall:
        overall.advance("NVDA-FY2024")
        overall.advance("AMD-FY2023")
        overall.write("stored something")

    bar = bars[0]
    assert (bar.options["total"], bar.options["unit"]) == (3, "doc")
    assert bar.n == 2
    assert bar.postfix == "AMD-FY2023"
    assert bar.lines == ["stored something"]
    assert bar.closed


def test_a_line_printed_during_a_run_goes_through_the_bar(bars):
    """Plain printing would interleave with the bar's own redraw and shred both."""
    with overall_bar(1, unit="doc", description="EDGAR") as overall:
        overall.advance()
        overall.write("one line")

    assert bars[0].postfix is None
    assert bars[0].lines == ["one line"]


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
