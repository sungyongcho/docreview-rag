"""Fixed local-checkout command registry shared by the API and README."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

type CommandCategory = Literal["inspect", "verify", "service"]


@dataclass(frozen=True, slots=True)
class OperatorCommand:
    """One exact argv operation exposed to the loopback operator UI."""

    command_id: str
    label: str
    description: str
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: int
    category: CommandCategory
    confirmation: str | None = None
    environment: tuple[tuple[str, str], ...] = ()


COMMANDS: MappingProxyType[str, OperatorCommand] = MappingProxyType(
    {
        command.command_id: command
        for command in (
            OperatorCommand(
                "git-status",
                "Git status",
                "Show branch plus staged, unstaged, and untracked paths.",
                ("git", "status", "--short", "--branch"),
                Path("."),
                30,
                "inspect",
            ),
            OperatorCommand(
                "python-lint",
                "Python lint",
                "Check application, tests, and scripts without rewriting files.",
                (".venv/bin/ruff", "check", "app", "tests", "scripts"),
                Path("."),
                300,
                "verify",
            ),
            OperatorCommand(
                "python-format-check",
                "Python format check",
                "Report files Ruff would reformat without changing them.",
                (".venv/bin/ruff", "format", "--check", "app", "tests"),
                Path("."),
                300,
                "verify",
            ),
            OperatorCommand(
                "python-tests-offline",
                "Python tests · offline",
                "Run the suite without live PostgreSQL cases or provider requests.",
                (".venv/bin/pytest", "-q", "-m", "not live_postgres"),
                Path("."),
                1_800,
                "verify",
            ),
            OperatorCommand(
                "python-tests-postgres",
                "Python tests · PostgreSQL",
                "Require the live PostgreSQL marker instead of silently skipping it.",
                (
                    ".venv/bin/pytest",
                    "-q",
                    "-m",
                    "live_postgres",
                    "--require-live-postgres",
                ),
                Path("."),
                1_800,
                "verify",
            ),
            OperatorCommand(
                "web-tests",
                "Web tests",
                "Run the Vitest component and client-contract suite.",
                ("npm", "test"),
                Path("web"),
                600,
                "verify",
            ),
            OperatorCommand(
                "web-typecheck",
                "Web typecheck",
                "Run TypeScript without emitting build output.",
                ("npm", "run", "typecheck"),
                Path("web"),
                600,
                "verify",
            ),
            OperatorCommand(
                "web-build",
                "Web production build",
                "Build the current static Next source in an isolated temporary checkout.",
                (".venv/bin/python", "scripts/check_web_build.py"),
                Path("."),
                1_200,
                "verify",
            ),
            OperatorCommand(
                "db-migrate-plan",
                "Plan DB migration",
                "Inspect pending data-preserving schema migrations without changing the database.",
                (".venv/bin/python", "-m", "app.db.migrate", "--plan"),
                Path("."),
                120,
                "inspect",
            ),
            OperatorCommand(
                "db-migrate-apply",
                "Apply DB migration",
                "Apply pending additive migrations while preserving corpus and run rows.",
                (".venv/bin/python", "-m", "app.db.migrate", "--apply"),
                Path("."),
                300,
                "service",
                (
                    "Add the pending usage-accounting columns and constraints to the local "
                    "database. Existing rows are preserved."
                ),
            ),
            OperatorCommand(
                "db-start",
                "Start PostgreSQL",
                "Start the local pgvector service and retain its existing volume.",
                ("docker", "compose", "up", "-d", "db"),
                Path("."),
                300,
                "service",
                "Start the local PostgreSQL container. Existing volume data is retained.",
            ),
            OperatorCommand(
                "db-stop",
                "Stop PostgreSQL",
                "Stop the local database without deleting its volume.",
                ("docker", "compose", "stop", "db"),
                Path("."),
                300,
                "service",
                "Stop PostgreSQL. Running API and tests may become unavailable.",
            ),
            OperatorCommand(
                "app-start",
                "Build and start app",
                "Build the local image and start the app with its database dependency.",
                ("docker", "compose", "up", "--build", "-d", "app"),
                Path("."),
                1_800,
                "service",
                "Build and start the local app container. This may use substantial CPU and time.",
            ),
            OperatorCommand(
                "app-stop",
                "Stop app",
                "Stop the local app container while leaving PostgreSQL unchanged.",
                ("docker", "compose", "stop", "app"),
                Path("."),
                300,
                "service",
                "Stop the local app API. The host Operations page remains available.",
            ),
        )
    }
)


def render_commands_markdown() -> str:
    """Render the README command table from the executable registry."""
    lines = [
        "| ID | Command | Purpose | Confirmation |",
        "|---|---|---|---|",
    ]
    for command in COMMANDS.values():
        argv = " ".join(command.argv).replace("|", "\\|")
        confirmation = "required" if command.confirmation else "no"
        lines.append(
            f"| `{command.command_id}` | `{argv}` | {command.description} | {confirmation} |"
        )
    return "\n".join(lines)
