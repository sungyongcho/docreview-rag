"""One deterministic Markdown table renderer shared by every evaluation report."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

ColumnAlignment = Literal["left", "right"]

_ALIGNMENT_RULES: Final[dict[ColumnAlignment, str]] = {"left": "---", "right": "---:"}


def escape_cell(value: str) -> str:
    """Return one table-safe rendering of a cell's text.

    Parameters
    ----------
    value : str
        Cell text from any source, including model output and manifest ids.

    Returns
    -------
    str
        Text whose pipes are escaped and whose whitespace runs are single spaces.

    Notes
    -----
    A raw pipe shifts every later column and a raw newline splits one row into
    two, so an unescaped cell does not corrupt the row it came from — it
    fabricates a row the reader has no reason to distrust. Escaping here means no
    caller has to constrain the values it renders.
    """
    return " ".join(value.replace("|", r"\|").split())


def markdown_table(
    headers: Sequence[str],
    alignments: Sequence[ColumnAlignment],
    rows: Sequence[Sequence[str]],
) -> str:
    """Render one Markdown table with escaped cells and a fixed column count.

    Parameters
    ----------
    headers : Sequence[str]
        Nonempty column headings.
    alignments : Sequence[ColumnAlignment]
        One alignment per column, in heading order.
    rows : Sequence[Sequence[str]]
        Body rows, each carrying exactly one cell per column.

    Returns
    -------
    str
        Heading row, alignment rule, and body rows joined by newlines.

    Raises
    ------
    ValueError
        If ``headers`` is empty or a row or the alignment list has a different
        width than the headings.

    Notes
    -----
    An empty ``rows`` renders a heading-only table on purpose: whether zero rows
    is an error belongs to the report that knows what zero means, not here.
    """
    if not headers:
        raise ValueError("headers must not be empty")
    if len(alignments) != len(headers):
        raise ValueError("one alignment is required per column")
    for index, row in enumerate(rows):
        if len(row) != len(headers):
            raise ValueError(f"row {index} has {len(row)} cells for {len(headers)} columns")

    lines = [
        _row(headers),
        "|" + "|".join(_ALIGNMENT_RULES[alignment] for alignment in alignments) + "|",
    ]
    lines.extend(_row(row) for row in rows)
    return "\n".join(lines)


def _row(cells: Sequence[str]) -> str:
    """Render one escaped, pipe-delimited table row."""
    return "| " + " | ".join(escape_cell(cell) for cell in cells) + " |"
