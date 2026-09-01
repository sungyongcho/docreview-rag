"""Two-level progress display shared by the corpus acquisition commands.

A corpus build waits on two very different clocks: how many filings are left, and
how far the current multi-megabyte body has come. One bar cannot show both, and
showing only the first is what made these commands look hung — DART spends minutes
inside a single response, so a bar that ticks once per filing never moves.

Nothing here decides what to fetch. The acquisition modules take a ``ByteProgress``
hook and call it as bytes arrive; this module is the only place that knows the hook
is drawn as a bar, which keeps ``tqdm`` out of the fetch contracts entirely.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from tqdm import tqdm

# Absolute bytes read so far, and the length the response declared when it declared
# one. Absolute rather than incremental so a retried request can restart its own
# count without the display having to unwind anything.
ByteProgress = Callable[[int, int | None], None]


@contextmanager
def byte_bar(description: str) -> Iterator[ByteProgress]:
    """Draw one download as a byte-scaled bar and yield the hook that advances it.

    The bar leaves no trace when it closes: the completed downloads are reported by
    the caller as lines, and a screen of finished bars would bury them.

    Parameters
    ----------
    description : str
        What is downloading, spelled for a human — an issuer and a document.
    """
    with tqdm(unit="B", unit_scale=True, unit_divisor=1024, desc=description, leave=False) as bar:

        def report(read: int, total: int | None) -> None:
            """Synchronize the byte bar with the response's absolute progress."""
            if total is not None and bar.total != total:
                bar.total = total
            bar.n = read
            bar.refresh()

        yield report


class Overall:
    """The outer bar's handle: advance it, label it, and print past it.

    Printing goes through here because a plain ``print`` while a bar is on screen
    interleaves with the bar's own redraw and shreds both.
    """

    def __init__(self, bar: tqdm) -> None:
        self._bar = bar

    def advance(self, label: str = "") -> None:
        """Count one finished item, showing ``label`` as the position just reached."""
        self._bar.update(1)
        if label:
            self._bar.set_postfix_str(label)

    def write(self, line: str) -> None:
        """Emit one line above the bar without disturbing it."""
        self._bar.write(line)


@contextmanager
def overall_bar(total: int, *, unit: str, description: str) -> Iterator[Overall]:
    """Draw the outer bar counting whole filings, and yield its handle."""
    with tqdm(total=total, unit=unit, desc=description) as bar:
        yield Overall(bar)
