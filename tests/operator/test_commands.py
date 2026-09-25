"""Fixed local Operations registry tests."""

from pathlib import Path

from app.operator.commands import COMMANDS


def _render_commands_markdown() -> str:
    """Render the archived README command table from the executable registry."""
    lines = [
        "| ID | Target | Command | Purpose | Confirmation |",
        "|---|---|---|---|---|",
    ]
    for command in COMMANDS.values():
        argv = " ".join(command.argv).replace("|", "\\|")
        confirmation = "required" if command.confirmation else "no"
        lines.append(
            f"| `{command.command_id}` | {command.target.capitalize()} | `{argv}` | "
            f"{command.description} | {confirmation} |"
        )
    return "\n".join(lines)


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


def test_readme_command_table_matches_the_executable_registry():
    """Fail when documented buttons drift from the host command registry."""
    readme = Path("docs/README_archive.md").read_text(encoding="utf-8")
    documented = (
        readme.split("<!-- operator-commands:start -->", 1)[1]
        .split(
            "<!-- operator-commands:end -->",
            1,
        )[0]
        .strip()
    )
    assert documented == _render_commands_markdown()
