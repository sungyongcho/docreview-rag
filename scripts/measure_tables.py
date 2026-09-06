#!/usr/bin/env python3
"""Regenerate the M1.2 corpus measurements and per-document golden tuples."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from statistics import median

from bs4 import Tag

from app.ingestion.parser import leaf_blocks, normalize, read_source
from app.ingestion.tables import drop_empty, merge_unit_columns, table_to_markdown, to_grid

REPO = Path(__file__).resolve().parent.parent
PAREN_NUMBER = re.compile(r"^\(\s*[\d,.]+\s*\)$")


def _span(cell: Tag, name: str) -> int:
    try:
        return max(1, int(str(cell.get(name) or 1).strip() or 1))
    except TypeError, ValueError:
        return 1


def _percentile(values: list[int], fraction: float) -> int:
    """Return a deterministic nearest-rank percentile for a non-empty list."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _expanded_row_widths(table: Tag) -> list[int]:
    """Return declared row widths after colspan but before rectangular padding."""
    return [
        sum(_span(cell, "colspan") for cell in row.find_all(["td", "th"]))
        for row in table.find_all("tr")
    ]


def measure() -> tuple[dict[str, tuple[int, int, int, int]], dict[str, object]]:
    """Measure the fixed corpus without writing profiles or derived artifacts."""
    manifest = json.loads((REPO / "data/corpus/manifest.json").read_text())
    golden: dict[str, tuple[int, int, int, int]] = {}
    empty_ratios: list[float] = []
    before_widths: list[int] = []
    dropped_widths: list[int] = []
    after_widths: list[int] = []
    totals: Counter[str] = Counter()

    for entry in sorted(manifest, key=lambda item: (item["ticker"], item["report_date"])):
        doc_id = f"{entry['ticker']}-FY{entry['report_date'][:4]}"
        raw = read_source(REPO / entry["file"])
        tables = [block for block in leaf_blocks(normalize(raw)) if block.name == "table"]
        empty_outputs = expanded_cells = dropped_cells = collapsed_cells = 0

        for table in tables:
            row_widths = _expanded_row_widths(table)
            if row_widths and len(set(row_widths)) > 1:
                totals["ragged_tables"] += 1

            cells = table.find_all(["td", "th"])
            if cells:
                empty_ratios.append(
                    sum(not cell.get_text(" ", strip=True) for cell in cells) / len(cells)
                )
            for cell in cells:
                colspan = _span(cell, "colspan")
                rowspan = _span(cell, "rowspan")
                if colspan > 1:
                    totals["colspan_occurrences"] += 1
                    totals["colspan_covered_cells"] += colspan
                if rowspan > 1:
                    totals["rowspan_occurrences"] += 1
                if PAREN_NUMBER.fullmatch(cell.get_text(" ", strip=True)):
                    totals["parenthesized_number_cells"] += 1

            grid = to_grid(table)
            dropped = drop_empty(grid)
            collapsed = merge_unit_columns(dropped)
            expanded_cells += sum(len(row) for row in grid)
            dropped_cells += sum(len(row) for row in dropped)
            collapsed_cells += sum(len(row) for row in collapsed)
            if grid:
                before_widths.append(len(grid[0]))
            if dropped:
                dropped_widths.append(len(dropped[0]))
            if collapsed:
                after_widths.append(len(collapsed[0]))
            if not table_to_markdown(str(table)):
                empty_outputs += 1

        golden[doc_id] = (len(tables), empty_outputs, expanded_cells, collapsed_cells)
        totals["tables"] += len(tables)
        totals["empty_outputs"] += empty_outputs
        totals["expanded_cells"] += expanded_cells
        totals["dropped_cells"] += dropped_cells
        totals["collapsed_cells"] += collapsed_cells

    summary: dict[str, object] = dict(totals)
    summary["median_raw_cell_empty_ratio"] = round(median(empty_ratios), 3)
    summary["expanded_widths"] = {
        "p50": _percentile(before_widths, 0.50),
        "p90": _percentile(before_widths, 0.90),
        "max": max(before_widths),
    }
    summary["empty_axes_removed_widths"] = {
        "p50": _percentile(dropped_widths, 0.50),
        "p90": _percentile(dropped_widths, 0.90),
        "max": max(dropped_widths),
    }
    summary["collapsed_widths"] = {
        "p50": _percentile(after_widths, 0.50),
        "p90": _percentile(after_widths, 0.90),
        "max": max(after_widths),
    }
    return golden, summary


if __name__ == "__main__":
    measured_golden, measured_summary = measure()
    print("TABLES = {")
    for measured_doc_id, values in measured_golden.items():
        print(f"    {measured_doc_id!r}: {values},")
    print("}")
    print("\nSUMMARY =")
    print(json.dumps(measured_summary, indent=2, sort_keys=True))
