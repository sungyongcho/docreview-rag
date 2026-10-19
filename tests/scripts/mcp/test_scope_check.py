"""Scripted scope questions of the read-only MCP check."""

from scripts.mcp.scope_check import questions


def test_questions_expect_reads_only_after_retrieval():
    """Each question reads only chunks its own earlier calls returned."""
    schedule = {question.name: question for question in questions("AMD", 2023, 2024, 11, 22)}
    assert len(schedule) == 6
    first = schedule["first question accumulates both years"]
    assert first.reads == (11, 22)
    assert first.rejected == (0,)
    failed = schedule["failed comparison ends the run as a tool error"]
    assert failed.status == "tool_error"
    assert failed.reads == ()
    assert schedule["next question on the same connection starts empty"].reads == (22,)
