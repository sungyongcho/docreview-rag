"""Scripted scope questions of the read-only MCP check."""

import asyncio
from types import SimpleNamespace

import pytest

from app import config
from scripts.mcp.scope_check import check, questions
from tests.mcp.support import REPO_ROOT
from tests.scripts.mcp.live_database import seeded_database


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


@pytest.mark.live_postgres
def test_the_check_passes_on_a_seeded_two_year_corpus(tmp_path, monkeypatch):
    """Every scripted question reads what it should from a real database over real MCP.

    The server subprocess runs in an empty directory, so no environment file is read.
    """

    async def scenario() -> list[dict]:
        """Seed AMD 2023 and 2024, then run the check against that database."""
        async with seeded_database(["AMD-FY2023", "AMD-FY2024"]) as url:
            monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(database_url=url))
            monkeypatch.setenv("DATABASE_URL", url)
            return await check("AMD", [2023, 2024])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    rows = asyncio.run(scenario())
    assert len(rows) == 6
    assert all(row["passed"] for row in rows), rows
