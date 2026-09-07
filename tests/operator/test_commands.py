"""Fixed local Operations registry tests."""

from pathlib import Path

from app.operator.commands import COMMANDS, render_commands_markdown


def test_command_registry_contains_only_fixed_non_destructive_argv():
    """Exclude arbitrary shells, source rewrites, deployment, and data deletion."""
    assert set(COMMANDS) == {
        "git-status",
        "python-lint",
        "python-format-check",
        "python-tests-offline",
        "python-tests-postgres",
        "web-tests",
        "web-typecheck",
        "web-build",
        "schema-check",
        "schema-prepare",
        "db-start",
        "db-stop",
        "app-start",
        "app-stop",
    }
    argv = "\n".join(" ".join(command.argv) for command in COMMANDS.values())
    assert "rm " not in argv and "down -v" not in argv and "git commit" not in argv
    assert all(command.argv and command.timeout_seconds > 0 for command in COMMANDS.values())
    assert all(
        command.confirmation for command in COMMANDS.values() if command.category == "service"
    )


def test_markdown_renderer_is_derived_from_the_registry():
    """Render every executable command into one stable README table."""
    rendered = render_commands_markdown()
    assert rendered.count("\n|") == len(COMMANDS) + 1
    assert "`.venv/bin/python -m scripts.release.web_build`" in rendered
    assert "`docker compose --project-directory . -f docker/docker-compose.yml stop db`" in rendered


def test_readme_command_table_matches_the_executable_registry():
    """Fail when documented buttons drift from the host command registry."""
    readme = Path("README.md").read_text(encoding="utf-8")
    documented = (
        readme.split("<!-- operator-commands:start -->", 1)[1]
        .split(
            "<!-- operator-commands:end -->",
            1,
        )[0]
        .strip()
    )
    assert documented == render_commands_markdown()
