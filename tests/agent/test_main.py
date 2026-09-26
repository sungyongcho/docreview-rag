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
    ("option", "out_of_range"),
    [
        pytest.param("--k", ("0", "21"), id="k"),
        pytest.param("--max-iterations", ("0", "65"), id="max_iterations"),
    ],
)
def test_cli_rejects_out_of_range_limits_at_parse_time(option, out_of_range):
    """Fail as a usage error at both ends of the range before any runtime module loads."""
    from app.agent.__main__ import arguments

    for value in out_of_range:
        with pytest.raises(SystemExit):
            arguments(["--question", "q", option, value])


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


def test_cli_model_default_follows_the_agent_policy_default():
    """The command must not pick a different (and pricier) default model than the policy."""
    from app.agent.__main__ import arguments
    from app.openai_models import resolve_openai_model

    args = arguments(["--question", "q", "--provider", "openai"])

    assert args.model in (None, resolve_openai_model("agent").model)


def _slot_settings(key):
    """Build settings that select the dev key slot with the given key (None for no key)."""
    from app.config import Settings

    values = {
        "_env_file": None,
        "MODE": "dev",
        "DATABASE_URL": "postgresql+asyncpg://filing:filing@127.0.0.1:55439/filing",
    }
    if key is not None:
        values["OPENAI_API_KEY_LOCAL"] = key
    return Settings(**values)


def test_openai_provider_receives_the_mode_selected_key_and_the_engine_is_released(monkeypatch):
    """The openai path passes the slot key Settings resolved and disposes the pool it opened."""
    from app.agent import __main__ as entrypoint
    import app.agent.provider as provider_module
    import app.db.session as session_module

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("app.config.get_settings", lambda: _slot_settings("sk-local-slot-test"))
    disposed = []

    class FakeEngine:
        """Engine stand-in recording the pool release."""

        async def dispose(self):
            """Record that the pool was released."""
            disposed.append(True)

    monkeypatch.setattr(session_module, "engine", FakeEngine())
    captured = {}

    class FakeClient:
        """SDK stand-in recording its constructor arguments and failing every request."""

        base_url = "https://api.openai.com/v1"

        def __init__(self, **kwargs):
            captured.update(kwargs)

            async def create(**_):
                raise RuntimeError("offline")

            self.responses = type("Responses", (), {"create": staticmethod(create)})()

        async def close(self):
            """Nothing to release."""

    monkeypatch.setattr(provider_module, "AsyncOpenAI", FakeClient)

    args = entrypoint.arguments(["--question", "q", "--provider", "openai"])
    result = asyncio.run(entrypoint._run(args))

    assert result["status"] == "provider_error"
    assert captured.get("api_key") == "sk-local-slot-test"
    assert disposed == [True]


def test_openai_provider_requires_the_mode_selected_key_slot(monkeypatch):
    """A missing slot key is a usage error naming the slot, not an SDK message."""
    from app.agent import __main__ as entrypoint

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("app.config.get_settings", lambda: _slot_settings(None))

    args = entrypoint.arguments(["--question", "q", "--provider", "openai"])
    with pytest.raises(SystemExit, match="OPENAI_API_KEY_LOCAL"):
        asyncio.run(entrypoint._run(args))
