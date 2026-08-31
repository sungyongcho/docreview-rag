"""Agent entry point: argument bounds, the offline demo, guards, and exit codes."""

import asyncio
import json
import os
import subprocess
import sys

import pytest


def test_cli_arguments_default_to_the_offline_demo():
    """Default to the deterministic provider and the documented limits."""
    from app.agent.__main__ import arguments

    args = arguments(["--question", "How much did revenue increase?"])

    assert args.provider == "deterministic"
    assert args.k == 5
    assert args.max_iterations == 8
    assert args.mcp is False


@pytest.mark.parametrize(
    "argv",
    [
        ["--question", "q", "--k", "0"],
        ["--question", "q", "--k", "21"],
        ["--question", "q", "--max-iterations", "0"],
        ["--question", "q", "--max-iterations", "65"],
    ],
)
def test_cli_rejects_out_of_range_limits_at_parse_time(argv):
    """Fail as a usage error before any runtime module loads."""
    from app.agent.__main__ import arguments

    with pytest.raises(SystemExit):
        arguments(argv)


def test_main_requires_a_question_before_loading_runtime_modules():
    """Exit with the usage message, not a settings traceback, when no question is given."""
    from app.agent import __main__ as entrypoint

    with pytest.raises(SystemExit, match="--question is required"):
        entrypoint.main([])
    with pytest.raises(SystemExit, match="--question is required"):
        entrypoint.main(["--question", "   "])


def test_demo_provider_scripts_one_search_and_an_honest_absent_answer():
    """Script one real search followed by an absent answer that cites nothing."""
    from app.agent.__main__ import _demo_provider

    provider = _demo_provider("How much did revenue increase?", 5)

    first = asyncio.run(provider.turn("", [], [], max_output_tokens=32))
    second = asyncio.run(provider.turn("", [], [], max_output_tokens=32))
    assert first.tool_calls[0].name == "search_filings"
    search = json.loads(first.tool_calls[0].arguments_json)
    assert search["query"] == "How much did revenue increase?"
    assert search["k"] == 5
    final = json.loads(second.tool_calls[0].arguments_json)
    assert second.tool_calls[0].name == "final_answer"
    assert final["label"] == "NOT_IN_DOCS" and final["citations"] == []


def test_main_exits_nonzero_for_a_terminal_failure_status(monkeypatch, capsys):
    """Print the payload and exit 1 when the run did not end in ok."""
    from app.agent import __main__ as entrypoint

    async def failing_run(args):
        """Return a terminal provider failure without touching the runtime."""
        return {"status": "provider_error", "failure": "provider request failed"}

    async def passing_run(args):
        """Return a grounded terminal result without touching the runtime."""
        return {"status": "ok"}

    monkeypatch.setattr(entrypoint, "_run", failing_run)
    with pytest.raises(SystemExit) as failure:
        entrypoint.main(["--question", "q"])
    assert failure.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "provider_error"

    monkeypatch.setattr(entrypoint, "_run", passing_run)
    entrypoint.main(["--question", "q"])
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_cli_help_is_independent_of_runtime_settings() -> None:
    """Print help under a configuration the settings schema rejects."""
    environment = {**os.environ, "EMBEDDING_BATCH_SIZE": "0"}

    result = subprocess.run(
        [sys.executable, "-m", "app.agent", "--help"],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Run the evidence-checked filing agent" in result.stdout


def test_missing_question_is_a_usage_error_even_under_invalid_settings() -> None:
    """Reject a missing question with the usage message when settings cannot load."""
    environment = {**os.environ, "EMBEDDING_BATCH_SIZE": "0"}

    result = subprocess.run(
        [sys.executable, "-m", "app.agent"],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--question is required unless --mcp is set" in result.stderr
    assert "ValidationError" not in result.stderr
