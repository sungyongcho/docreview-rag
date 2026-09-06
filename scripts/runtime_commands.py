"""Share local web reset and corpus operations with the shell commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from scripts.local_env import load_local_environment
from scripts.local_operator import LocalOperator, OperatorLifecycleError
from scripts.local_stack import run

ROOT = Path(__file__).resolve().parents[1]
WARNING = """WARNING: This permanently deletes the project's database, downloaded
SEC/DART filings, evaluation results, and saved local model settings.
You must download the SEC/DART data again and repeat the setup and
processing steps to restore full functionality.
Use the terminal commands in rag-help or the development web interface
started by Quick Start. Code, .env, keys, and host Ollama are preserved."""
RECOVERY = """Next steps: download SEC/DART filings, ingest manifests, generate embeddings,
rebuild BM25, and configure your answer model. Run rag-help for commands.
In the development web UI, open Settings > Data & help > Reset runtime data,
select View reset status, then Clear browser data and start again.
Continue the Build steps in the web UI. Public read-only deployments cannot
perform these administrator operations."""


class RuntimeCommandError(RuntimeError):
    """A local operation could not safely complete."""


class LocalClient:
    """Use the same loopback endpoints and credentials as the development browser."""

    def __init__(self, base: str, origin: str, token: str = "") -> None:
        """Retain credentials privately and disable proxy routing."""
        self.base = base
        self.origin = origin
        self.token = token
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path: str, body: dict | None = None) -> dict:
        """Issue one request without retrying potentially accepted mutations."""
        headers = {"Origin": self.origin, "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeCommandError(
                f"Request rejected (HTTP {error.code}). Check the web UI for diagnostics. "
                "No automatic retry was attempted."
            ) from error
        except (URLError, TimeoutError) as error:
            raise RuntimeCommandError(
                "Local service unavailable or response timed out. Check the web UI before "
                "retrying: an operation may already have started."
            ) from error


def operator_client(root: Path) -> LocalClient:
    """Require the existing authenticated host operator rather than create another reset owner."""
    operator = LocalOperator(root)
    environment = operator.environment()
    base = environment["NEXT_PUBLIC_OPERATOR_BASE_URL"]
    if not base:
        raise RuntimeCommandError("Start the development stack first: rag-dev up -d")
    bindings = load_local_environment(root / ".env", mode="dev")
    origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
    return LocalClient(base, origin, environment["NEXT_PUBLIC_OPERATOR_TOKEN"])


def fresh_start(root: Path, *, timeout: float = 1800) -> int:
    """Confirm the web deletion preview, wait for its result, then rebuild the dev stack."""
    print(WARNING)
    if not sys.stdin.isatty():
        raise RuntimeCommandError("Run interactively to review and type the deletion confirmation.")
    client = operator_client(root)
    preview = client.request("/wipe/preview", {})
    target = preview["target"]
    print(f"Checkout: {root}\nDatabase volume: {target['volume']}")
    print(f"Runtime files to delete: {len(target['files'])}\nNo backup will be created.")
    answer = input(f"Type {preview['confirmation']} to permanently reset this runtime: ")
    if answer != preview["confirmation"]:
        print("Cancelled; no data was deleted.")
        return 0
    if time.time() >= preview["expires"]:
        raise RuntimeCommandError(
            "The preview expired. Run the command again to review new targets."
        )
    result = client.request("/wipe", {"token": preview["token"], "confirmation": answer})
    reset_id = result.get("id")
    deadline = time.monotonic() + timeout
    previous = None
    while result["status"] == "running":
        stage = result.get("stage", "running")
        if stage != previous:
            print(f"Reset: {stage}", flush=True)
            previous = stage
        if time.monotonic() >= deadline:
            raise RuntimeCommandError(
                "Reset is still running. Check View reset status in the web UI."
            )
        time.sleep(1)
        result = client.request("/wipe")
        if reset_id and result.get("id") != reset_id:
            raise RuntimeCommandError(
                "Reset identity changed. Check the web UI; rebuilding stopped."
            )
    if result["status"] != "succeeded":
        raise RuntimeCommandError(
            f"Reset ended with status {result['status']}. Some data may already be deleted. "
            "Review recovery instructions in the web UI. Rebuilding was not started."
        )
    print("Runtime reset complete. Rebuilding the application image without cached layers.")
    code = run("dev", ["build", "--no-cache", "app"], root=root)
    if code:
        print("Data was reset, but the build failed. Correct the build error before restarting.")
        return code
    code = run("dev", ["up", "-d", "--no-build", "--force-recreate"], root=root)
    if code:
        print("Data was reset and the image built, but service startup failed. Run rag-diagnose.")
        return code
    print(RECOVERY)
    return 0


def corpus(args: argparse.Namespace, root: Path) -> int:
    """Submit the same corpus jobs used by Build and leave their progress in the shared Jobs UI."""
    bindings = load_local_environment(root / ".env", mode="dev")
    origin = f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}"
    client = LocalClient(origin + "/docreview-rag-agent/api/admin", origin)
    if args.kind == "readiness":
        print(
            json.dumps(
                LocalClient(origin + "/docreview-rag-agent/api", origin).request("/ready/"),
                indent=2,
            )
        )
        return 0
    if args.kind in {"status", "inspect"}:
        path = "/corpus/jobs/" if args.kind == "status" else "/corpus/"
        print(json.dumps(client.request(path), indent=2))
        return 0
    body = {"kind": args.kind, "identifiers": args.identifier, "years": args.year}
    if args.manifest:
        body["manifest"] = args.manifest
    if args.selection:
        body["selection_id"] = args.selection
    if args.expected_documents is not None:
        body["expected_documents"] = args.expected_documents
    print(f"Queue {args.kind} for {root}.")
    print("Downloads contact SEC/DART. Embeddings may incur configured provider charges.")
    if not sys.stdin.isatty():
        raise RuntimeCommandError("Run interactively to confirm this corpus operation.")
    if input("Continue? [y/N] ").lower() not in {"y", "yes"}:
        print("Cancelled; no job was submitted.")
        return 0
    result = client.request("/corpus/jobs/", body)
    print(json.dumps(result, indent=2))
    print("Track this job with rag-corpus status or the development web Jobs panel.")
    return 0


def main() -> int:
    """Expose help without connecting to services or mutating runtime state."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "fresh-start",
        help="Confirm a destructive reset, rebuild, and restart.",
        description=WARNING
        + "\nStart rag-dev up -d first. An interactive confirmation is required.",
    )
    jobs = commands.add_parser("corpus", help="Use the same corpus jobs as the development web UI.")
    jobs.add_argument(
        "kind",
        choices=[
            "status",
            "inspect",
            "readiness",
            "acquire_edgar",
            "acquire_dart",
            "ingest_manifest",
            "backfill_embeddings",
            "rebuild_bm25",
        ],
    )
    jobs.add_argument(
        "--identifier",
        action="append",
        default=[],
        help="SEC ticker or DART stock code; repeat as needed.",
    )
    jobs.add_argument(
        "--year", type=int, action="append", default=[], help="DART filing year; repeat as needed."
    )
    jobs.add_argument("--manifest", help="Corpus-relative manifest path, as shown in the Build UI.")
    jobs.add_argument("--selection", help="Explicit processing selection ID from the Build UI.")
    jobs.add_argument("--expected-documents", type=int)
    args = parser.parse_args()
    try:
        return fresh_start(ROOT) if args.command == "fresh-start" else corpus(args, ROOT)
    except (RuntimeCommandError, OperatorLifecycleError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except EOFError, KeyboardInterrupt:
        print(
            "Stopped waiting. If a reset/job was submitted, check its status in the web UI.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
