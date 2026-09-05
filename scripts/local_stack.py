"""Select a local Compose mode and own its optional host Operations service."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from scripts.local_env import LocalEnvironmentError, load_local_environment
from scripts.local_operator import LocalOperator, OperatorLifecycleError

ROOT = Path(__file__).resolve().parents[1]


def compose_environment(mode: str, bindings: dict[str, str]) -> dict[str, str]:
    """Preserve unrelated settings while making mode and browser routing explicit."""
    environment = dict(os.environ)
    for key in (
        "COMPOSE_FILE",
        "COMPOSE_PROFILES",
        "NEXT_PUBLIC_API_BASE_URL",
        "NEXT_PUBLIC_OPERATOR_TOKEN",
        "NEXT_PUBLIC_OPERATOR_BASE_URL",
    ):
        environment.pop(key, None)
    return (
        environment
        | bindings
        | {
            "MODE": mode,
            "DOCREVIEW_ADMIN_MODE": "live" if mode == "dev" else "readonly",
            "NEXT_PUBLIC_ADMIN_MODE": "live" if mode == "dev" else "canned",
            "NEXT_PUBLIC_API_BASE_URL": "/docreview-rag-agent/api",
            "NEXT_PUBLIC_OPERATOR_TOKEN": "",
            "NEXT_PUBLIC_OPERATOR_BASE_URL": "",
            "HOST_GID": environment.get("HOST_GID", str(os.getgid())),
        }
    )


def compose_command(root: Path, mode: str, arguments: list[str]) -> list[str]:
    """Use explicit files and a stable project name from any working directory."""
    return [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "--env-file",
        str(root / ".env") if (root / ".env").exists() else os.devnull,
        "-p",
        root.name,
        "-f",
        str(root / "docker" / "docker-compose.yml"),
        "-f",
        str(root / "docker" / f"docker-compose.{mode}.yml"),
        *arguments,
    ]


def run(mode: str, arguments: list[str], *, root: Path = ROOT) -> int:
    """Coordinate up/down with authenticated Operations, preserving user data."""
    arguments = arguments or ["up", "-d"]
    action = arguments[0]
    if action == "down" and any(value in {"-v", "--volumes"} for value in arguments[1:]):
        raise LocalEnvironmentError(
            "rag down preserves data volumes; use an explicit Docker command for volume deletion"
        )
    bindings = load_local_environment(root / ".env", mode=mode)
    environment = compose_environment(mode, bindings)
    operator = LocalOperator(root)
    newly_started = False
    if mode == "prod" and action in {"up", "start", "restart", "down"}:
        operator.stop()
    elif mode == "dev":
        if action == "up":
            previous = operator.environment()
            environment.update(operator.start(bindings))
            newly_started = (
                previous["NEXT_PUBLIC_OPERATOR_TOKEN"] != environment["NEXT_PUBLIC_OPERATOR_TOKEN"]
            )
        else:
            environment.update(operator.environment())
    detached = any(value in {"-d", "--detach"} for value in arguments[1:])
    try:
        result = subprocess.run(
            compose_command(root, mode, arguments), cwd=root, env=environment, check=False
        )
    except KeyboardInterrupt:
        if newly_started and detached:
            operator.stop()
        return 130
    finally:
        if mode == "dev" and (action == "down" or (action == "up" and not detached)):
            operator.stop()
    if result.returncode != 0 and newly_started and detached:
        operator.stop()
    if result.returncode == 0 and action == "up":
        print(
            f"{mode.upper()} · http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}/docreview-rag-agent/"
        )
    return result.returncode


def main() -> None:
    """Accept an explicit mode followed by ordinary Docker Compose arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dev", "prod"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        raise SystemExit(run(args.mode, args.arguments))
    except (LocalEnvironmentError, OperatorLifecycleError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
