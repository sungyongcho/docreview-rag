"""Expose explicit mode commands without legacy shell aliases or implicit deletion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]


def parser(mode: str) -> argparse.ArgumentParser:
    """Describe mode actions, with explicit locality and reset boundaries."""
    result = argparse.ArgumentParser(
        prog=f"rag-{mode}", description="Manage this checkout locally; never deploy.", color=False
    )
    actions = result.add_subparsers(dest="action", required=True)
    start = actions.add_parser("start", help="Start without resetting existing data.")
    start.add_argument("--local", action="store_true")
    start.add_argument(
        "--ready", action="store_true", help="Restore or reuse saved local PROD data."
    )
    start.add_argument("--artifacts", type=Path)
    start.add_argument("--timeout", type=float, default=180)
    actions.add_parser("status", help="Inspect containers without starting them.")
    logs = actions.add_parser("logs", help="Read container logs.")
    logs.add_argument("service", nargs="?")
    logs.add_argument("--follow", "-f", action="store_true")
    logs.add_argument("--tail", type=int, default=100)
    actions.add_parser("stop", help="Stop containers; preserve data.")
    actions.add_parser("restart", help="Recreate services in the selected mode; preserve data.")
    doctor = actions.add_parser(
        "doctor", help="Diagnose the local environment and model connection."
    )
    doctor.add_argument("arguments", nargs=argparse.REMAINDER)
    compose = actions.add_parser("compose", help="Pass explicit arguments to Docker Compose.")
    compose.add_argument("arguments", nargs=argparse.REMAINDER)
    help_action = actions.add_parser("help", help="Show help for one command.")
    help_action.add_argument("topic", nargs="?")
    prepare = actions.add_parser("prepare", help="Restore verified saved data for local PROD.")
    prepare.add_argument("--local", action="store_true", required=True)
    prepare.add_argument("--artifacts", type=Path)
    prepare.add_argument("--check", action="store_true")
    for name in ("corpus", "schema"):
        command = actions.add_parser(name, help=f"Use DEV {name} operations.", add_help=False)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    reset = actions.add_parser("reset", help="Preview and confirm deletion; remain stopped.")
    reset.add_argument("target", choices=("data", "environment"))
    reset.add_argument("--local", action="store_true", required=True)
    reset.add_argument("--all-modes", action="store_true")
    reset.add_argument("--status", action="store_true")
    scope = reset.add_mutually_exclusive_group()
    scope.add_argument("--keep-sources", action="store_true")
    scope.add_argument("--sample", action="store_true")
    return result


def module(root: Path, name: str, arguments: list[str]) -> int:
    """Run an existing operation in the same interpreter and exact checkout."""
    return subprocess.run(
        [sys.executable, "-m", name, *arguments], cwd=root, check=False
    ).returncode


def require_running_mode(root: Path, mode: str) -> None:
    """Read the actual local server mode before a data action can reach the shared database."""
    from scripts.stack.environment import load_local_environment

    bindings = load_local_environment(root / ".env", mode=mode)
    url = (
        f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}/docreview-rag/api/ready/"
    )
    try:
        response = build_opener(ProxyHandler({})).open(url, timeout=5)
    except HTTPError as error:
        if error.code != 503:
            raise
        response = error
    with response:
        observed = json.load(response)
    if observed.get("mode") != "runtime" or observed.get("environment") != mode:
        raise ValueError(f"The local server is not {mode.upper()}; no data was changed.")


def dispatch(mode: str, args: argparse.Namespace, root: Path) -> int:
    """Validate intent before calling any existing implementation or touching services."""
    if args.action == "prepare" or (args.action == "start" and args.ready):
        if mode != "prod":
            raise ValueError("DEV has no ready-data shortcut. Use rag-dev corpus or the web UI.")
        if not args.local:
            raise ValueError("Preparing saved PROD data requires --local.")
        from deploy.gcp.verify_artifacts import validate_artifacts
        from scripts.stack.prod import artifact_directory, prepare

        bundle = artifact_directory(root, args.artifacts)
        validate_artifacts(bundle)
        if args.action == "start":
            from scripts.stack.quickstart import quickstart

            if args.timeout <= 0:
                raise ValueError("Startup timeout must be positive.")
            result = quickstart(root, mode=mode, timeout=args.timeout)
            if result:
                return result
        return prepare(
            root, artifacts=bundle, check=args.check if args.action == "prepare" else False
        )
    if args.action in {"corpus", "schema"}:
        if mode != "dev":
            raise ValueError(f"{args.action} operations require rag-dev; PROD is read-only.")
        if (
            args.action == "schema"
            and args.arguments
            and args.arguments[0] in {"prepare", "recreate"}
            and not any(flag in args.arguments for flag in ("--help", "-h"))
        ):
            from scripts.stack.prod import LocalDatabase

            if LocalDatabase(root).volume() != f"{root.name}_pg_data":
                raise ValueError("The active database is not DEV; no schema or data was changed.")
        return module(
            root,
            "scripts.stack.commands" if args.action == "corpus" else "scripts.schema",
            ["corpus", *args.arguments] if args.action == "corpus" else args.arguments,
        )
    if args.action == "reset":
        if args.target == "environment":
            if not args.all_modes or args.keep_sources or args.sample:
                raise ValueError(
                    "Environment reset requires --local --all-modes; no data-only options apply."
                )
            from scripts.stack.fresh import start_fresh, status

            return (
                status(root, "start-fresh")
                if args.status
                else start_fresh(root, no_start=True, runtime_only=True)
            )
        if args.all_modes:
            raise ValueError("--all-modes applies only to reset environment.")
        if mode != "dev":
            raise ValueError("Local PROD data reset is not connected. No data was changed.")
        if args.status:
            from scripts.stack.commands import reset_status

            return reset_status(root)
        require_running_mode(root, mode)
        options = ["recreate"]
        if args.keep_sources:
            options.append("--keep-sources")
        if args.sample:
            options.append("--sample")
        return module(root, "scripts.schema", options)
    if args.action == "start":
        from sqlalchemy.exc import SQLAlchemyError

        from scripts.stack.quickstart import quickstart

        if args.artifacts:
            raise ValueError("--artifacts requires start --local --ready.")
        if args.timeout <= 0:
            raise ValueError("Startup timeout must be positive.")
        try:
            return quickstart(root, mode=mode, timeout=args.timeout)
        except SQLAlchemyError as error:
            raise RuntimeError(
                f"Local database startup failed ({type(error).__name__}); data was preserved."
            ) from None
    if args.action == "doctor":
        if mode == "prod" and "--setup" in args.arguments:
            raise ValueError("Local model setup belongs to rag-dev doctor --setup.")
        return module(root, "scripts.diagnostics.ollama", args.arguments)
    from scripts.stack.__main__ import run

    if args.action == "compose":
        if not args.arguments:
            raise ValueError("compose requires an explicit Docker Compose command.")
        return run(mode, args.arguments, root=root)
    if args.action == "logs":
        values = ["logs", "--tail", str(args.tail)]
        if args.follow:
            values.append("--follow")
        if args.service:
            values.append(args.service)
        return run(mode, values, root=root)
    values = {
        "status": ["ps", "--all"],
        "stop": ["stop"],
        "restart": ["up", "-d", "--force-recreate"],
    }[args.action]
    return run(mode, values, root=root)


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    """Return actionable errors without silently translating retired commands."""
    values = list(sys.argv[1:] if argv is None else argv)
    if not values or values[0] not in {"dev", "prod"}:
        print("Usage: python -m scripts.stack.cli {dev|prod} <command>", file=sys.stderr)
        return 2
    mode = values.pop(0)
    cli = parser(mode)
    if not values:
        cli.print_help()
        return 0
    if values[0] == "help":
        values = [*values[1:], "--help"]
    # Pass operation flags to their existing parsers, including nested --help.
    if values[0] in {"corpus", "schema", "doctor", "compose"}:
        args = argparse.Namespace(action=values[0], arguments=values[1:])
    else:
        args = cli.parse_args(values)
    try:
        return dispatch(mode, args, root)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
