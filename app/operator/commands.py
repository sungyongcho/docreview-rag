"""Fixed local-checkout command registry shared by the API and README."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

type CommandCategory = Literal["inspect", "verify", "service"]
type CommandTarget = Literal["python", "web", "database", "app"]


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
    target: CommandTarget = field(kw_only=True)
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
                target="app",
            ),
            OperatorCommand(
                "python-lint",
                "Python lint",
                "Check application, tests, and scripts without rewriting files.",
                (".venv/bin/ruff", "check", "app", "tests", "scripts"),
                Path("."),
                300,
                "verify",
                target="python",
            ),
            OperatorCommand(
                "python-format-check",
                "Python format check",
                "Report files Ruff would reformat without changing them.",
                (".venv/bin/ruff", "format", "--check", "app", "tests"),
                Path("."),
                300,
                "verify",
                target="python",
            ),
            OperatorCommand(
                "python-tests-offline",
                "Python tests · offline",
                "Run the suite without live PostgreSQL cases or provider requests.",
                (".venv/bin/pytest", "-q", "-m", "not live_postgres"),
                Path("."),
                1_800,
                "verify",
                target="python",
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
                target="database",
            ),
            OperatorCommand(
                "web-tests",
                "Web tests",
                "Run the Vitest component and client-contract suite.",
                ("npm", "test"),
                Path("web"),
                600,
                "verify",
                target="web",
            ),
            OperatorCommand(
                "web-typecheck",
                "Web typecheck",
                "Run TypeScript without emitting build output.",
                ("npm", "run", "typecheck"),
                Path("web"),
                600,
                "verify",
                target="web",
            ),
            OperatorCommand(
                "web-build",
                "Web production build",
                "Build the current static Next source in an isolated temporary checkout.",
                (".venv/bin/python", "scripts/release/web_build.py"),
                Path("."),
                1_200,
                "verify",
                target="web",
            ),
            OperatorCommand(
                "schema-check",
                "Check schema",
                "Inspect this checkout's local database schema without changing data.",
                (".venv/bin/python", "-m", "scripts.schema", "check"),
                Path("."),
                60,
                "verify",
                target="database",
            ),
            OperatorCommand(
                "schema-prepare",
                "Prepare empty schema",
                "Create schema objects only in an empty local database; preserve existing data.",
                (".venv/bin/python", "-m", "scripts.schema", "prepare"),
                Path("."),
                120,
                "service",
                "Create the current schema only if the local database is empty. "
                "Existing data is never reset.",
                target="database",
            ),
            OperatorCommand(
                "db-start",
                "Start PostgreSQL",
                "Start the local pgvector service and retain its existing volume.",
                (
                    "docker",
                    "compose",
                    "--project-directory",
                    ".",
                    "-f",
                    "docker/docker-compose.yml",
                    "up",
                    "-d",
                    "db",
                ),
                Path("."),
                300,
                "service",
                "Start the local PostgreSQL container. Existing volume data is retained.",
                target="database",
            ),
            OperatorCommand(
                "db-stop",
                "Stop PostgreSQL",
                "Stop the local database without deleting its volume.",
                (
                    "docker",
                    "compose",
                    "--project-directory",
                    ".",
                    "-f",
                    "docker/docker-compose.yml",
                    "stop",
                    "db",
                ),
                Path("."),
                300,
                "service",
                "Stop PostgreSQL. Running API and tests may become unavailable.",
                target="database",
            ),
            OperatorCommand(
                "app-start",
                "Build and start app",
                "Build the local image and start the app with its database dependency.",
                (
                    "docker",
                    "compose",
                    "--project-directory",
                    ".",
                    "-f",
                    "docker/docker-compose.yml",
                    "up",
                    "--build",
                    "-d",
                    "app",
                ),
                Path("."),
                1_800,
                "service",
                "Build and start the local app container. This may use substantial CPU and time.",
                target="app",
            ),
            OperatorCommand(
                "app-stop",
                "Stop app",
                "Stop the local app container while leaving PostgreSQL unchanged.",
                (
                    "docker",
                    "compose",
                    "--project-directory",
                    ".",
                    "-f",
                    "docker/docker-compose.yml",
                    "stop",
                    "app",
                ),
                Path("."),
                300,
                "service",
                "Stop the local app API. The host Operations page remains available.",
                target="app",
            ),
        )
    }
)


def render_commands_markdown() -> str:
    """Render the README command table from the executable registry."""
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
