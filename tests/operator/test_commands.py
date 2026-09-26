"""Fixed local Operations registry tests."""

from app.operator.commands import COMMANDS


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
