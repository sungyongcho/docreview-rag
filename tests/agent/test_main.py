"""Agent entry point: argument defaults, the offline demo, and help."""

import json
import os
import subprocess
import sys


def test_cli_arguments_default_to_the_offline_demo():
    """Default to the deterministic provider and the documented limits."""
    from app.agent.__main__ import arguments

    args = arguments(["--question", "How much did revenue increase?"])

    assert args.provider == "deterministic"
    assert args.k == 5
    assert args.max_iterations == 8
    assert args.mcp is False


def test_demo_provider_scripts_one_search_and_an_honest_absent_answer():
    """Script one real search followed by an absent answer that cites nothing."""
    from app.agent.__main__ import _demo_provider

    provider = _demo_provider("How much did revenue increase?", 5)

    first, second = provider._turns
    assert first.tool_calls[0].name == "search_filings"
    assert json.loads(first.tool_calls[0].arguments_json)["query"] == (
        "How much did revenue increase?"
    )
    final = json.loads(second.tool_calls[0].arguments_json)
    assert second.tool_calls[0].name == "final_answer"
    assert final["label"] == "NOT_IN_DOCS" and final["citations"] == []


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
