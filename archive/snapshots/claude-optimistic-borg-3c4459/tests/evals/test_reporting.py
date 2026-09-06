"""Cell escaping and fixed-width rendering of the shared Markdown table."""

import pytest

from app.evals.reporting import escape_cell, markdown_table


def test_a_cell_can_never_add_a_column_or_a_row():
    """Keep pipes and newlines inside the cell that carried them."""
    assert escape_cell("TEST|X\nm3c-99") == r"TEST\|X m3c-99"
    assert escape_cell("  spaced   text  ") == "spaced text"
    assert escape_cell("plain") == "plain"


def test_alignment_rules_and_escaped_rows_render_exactly():
    """Render the heading, the per-column rule, and one escaped body row."""
    assert markdown_table(["Group", "Cases"], ["left", "right"], [["risk|policy", "6"]]) == (
        "| Group | Cases |\n|---|---:|\n| risk\\|policy | 6 |"
    )


def test_an_empty_body_renders_the_heading_and_a_misshaped_table_is_rejected():
    """Render zero rows as a heading, and refuse a table whose widths disagree."""
    assert markdown_table(["Group"], ["left"], []) == "| Group |\n|---|"

    with pytest.raises(ValueError, match="headers must not be empty"):
        markdown_table([], [], [])
    with pytest.raises(ValueError, match="one alignment is required per column"):
        markdown_table(["Group", "Cases"], ["left"], [])
    with pytest.raises(ValueError, match="row 1 has 1 cells for 2 columns"):
        markdown_table(["Group", "Cases"], ["left", "right"], [["a", "b"], ["c"]])
