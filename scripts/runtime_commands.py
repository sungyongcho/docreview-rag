"""Share local web reset and corpus operations with the shell commands."""

from __future__ import annotations

import argparse
import json
import os
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
                payload = json.load(response)
                if not isinstance(payload, dict):
                    raise RuntimeCommandError(
                        "Invalid response shape; use View reset status before any resubmission."
                    )
                return payload
        except HTTPError as error:
            diagnosis = {}
            try:
                payload = json.loads(error.read(16_384))
                if isinstance(payload, dict) and isinstance(payload.get("diagnosis"), dict):
                    diagnosis = payload["diagnosis"]
            except ValueError, OSError:
                pass
            actions = {
                "runtime_file_permission": (
                    "File access prerequisite failed. Review ownership and parent "
                    "permissions in Reset diagnosis; ask the owner to grant "
                    "access, then preview again."
                ),
                "active_jobs": (
                    "Active jobs block reset. Finish or cancel them in Jobs, then preview again."
                ),
                "active_local_operations": (
                    "Active local operations block reset. Wait for them to "
                    "finish, then preview again."
                ),
                "reset_precondition_failed": (
                    "A reset prerequisite failed. Open Reset runtime data > Reset "
                    "diagnosis and check rag-dev ps -a before requesting a new "
                    "preview."
                ),
                "reset_inspection_failed": (
                    "Reset inspection failed; the cause is unknown. Check Reset "
                    "diagnosis and rag-dev logs --tail 50."
                ),
            }
            code = diagnosis.get("code")
            diagnostic = (
                f"{code}: {actions[code]} "
                if isinstance(code, str) and code in actions
                else "Cause unavailable; check Reset diagnosis. "
            )
            raise RuntimeCommandError(
                f"Request rejected (HTTP {error.code}). "
                + diagnostic
                + (
                    "Preview rejected; no reset was submitted. "
                    if path == "/wipe/preview"
                    else (
                        "Execution may be uncertain. Run rag-fresh-start --status "
                        "before any resubmission. "
                    )
                )
                + "No automatic retry was attempted."
            ) from None
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeCommandError(
                "Invalid service response. Execution is uncertain; use View "
                "reset status. Do not resubmit."
            ) from error
        except (URLError, TimeoutError) as error:
            raise RuntimeCommandError(
                "Local service unavailable or response timed out. Check the web UI before "
                "retrying: an operation may already have started."
            ) from error


def operator_client(root: Path) -> LocalClient:
    """Require the existing authenticated host operator rather than create another reset owner."""
    base, origin, token = LocalOperator(root).client_connection()
    return LocalClient(base, origin, token)


def reset_status(root: Path) -> int:
    """Read reset evidence without prompting, retrying deletion, or needing a surviving .env."""
    result = operator_client(root).request("/wipe")
    status = result.get("status")
    if status not in {"idle", "running", "succeeded", "failed", "interrupted"}:
        raise RuntimeCommandError("Reset status is unavailable; do not resubmit deletion.")
    print("Reset status: " + status)
    known = {
        "app_stopped",
        "database_removed",
        "runtime_files_removed",
        "empty_schema_created",
        "extreme_complete",
    }
    completed = result.get("completed", [])
    if isinstance(completed, list):
        print(
            "Verified completed steps: "
            + ", ".join(step for step in completed if isinstance(step, str) and step in known)
        )
    if result.get("browser_cleared") is True:
        print("Browser deletion was acknowledged for this operation's browser/origin.")
    if status in {"failed", "interrupted"}:
        print(
            "Partial deletion is possible. Review reset diagnostics; do not automatically resubmit."
        )
    return 0 if status in {"idle", "succeeded"} else 1


def fresh_start(root: Path, *, timeout: float = 1800, extreme: bool = False) -> int:
    """Confirm the web deletion preview, wait for its result, then rebuild the dev stack."""
    print(
        WARNING
        if not extreme
        else (
            ("\033[1;31m" if sys.stdout.isatty() and "NO_COLOR" not in os.environ else "")
            + "+==================================================+\n"
            "| EXTREME RESET: NO BACKUP. IRREVERSIBLE DELETION.  |\n"
            "+==================================================+\n"
            "Deletes project .env files, untracked runtime/custom corpus and build caches, "
            "project volumes, and DocReview data in the browser that acknowledges this reset.\n"
            "Preserves tracked files and edits, Git history, unrelated files, host Ollama "
            "and external credentials. No automatic restart."
            + ("\033[0m" if sys.stdout.isatty() and "NO_COLOR" not in os.environ else "")
        )
    )
    if not sys.stdin.isatty():
        raise RuntimeCommandError("Run interactively to review and type the deletion confirmation.")
    client = operator_client(root)
    preview = client.request("/wipe/preview", {"extreme": True} if extreme else {})
    target = preview["target"]
    print(f"Checkout: {root}\nDatabase volume: {target['volume']}")
    print(f"Runtime files to delete: {len(target['files'])}\nNo backup will be created.")
    if extreme:
        print("Exact project-local deletion inventory:")
        for item in target["files"]:
            print("  File: " + json.dumps(item["path"]))
        for volume in target.get("extra_volumes", []):
            print("  Volume: " + json.dumps(volume))
        print(
            "Preserved: tracked files/edits, Git history, unrelated untracked files, "
            "host Python/Node dependencies, host Ollama, other browser origins/profiles."
        )
        if input(
            "Have you backed up .env, conversations and custom corpus data? [y/N] "
        ).strip().lower() not in {"y", "yes"}:
            print("Cancelled; no data was deleted.")
            return 0
    answer = input(
        f"Type {preview['confirmation']} to confirm irreversible deletion "
        "(the application cannot restore it; default No): "
    )
    if answer != preview["confirmation"]:
        print("Cancelled; no data was deleted.")
        return 0
    if time.time() >= preview["expires"]:
        raise RuntimeCommandError(
            "The preview expired. Run the command again to review new targets."
        )
    result = client.request(
        "/wipe",
        {"token": preview["token"], "confirmation": answer}
        | ({"backup_confirmed": True} if extreme else {}),
    )
    reset_id = result.get("id")
    if not isinstance(reset_id, str) or not reset_id:
        raise RuntimeCommandError(
            "Reset identity is missing. Use View reset status; do not resubmit."
        )
    if extreme:
        print(
            "Close other DocReview tabs to prevent saved state being restored. Open this URL in "
            "the browser holding your conversations, then clear and acknowledge its data:"
        )
        print(client.origin + "/docreview-rag-agent/reset-local/#" + reset_id, flush=True)

    deadline = time.monotonic() + timeout
    previous = None
    browser_reported = False
    while result["status"] == "running":
        if extreme and result.get("browser_cleared") and not browser_reported:
            print(
                "Browser DocReview deletion acknowledged; local deletion is not yet complete.",
                flush=True,
            )
            browser_reported = True
        stage = result.get("stage", "running")
        if stage not in {
            "running",
            "starting",
            "awaiting_browser",
            "hold_requests",
            "stop_app",
            "database_volume",
            "runtime_files",
            "empty_schema",
            "restart_app",
            "extreme_stop",
            "extreme_volumes",
        }:
            stage = "running (stage unavailable)"
        if stage != previous:
            print(f"Reset: {stage}", flush=True)
            previous = stage
        if time.monotonic() >= deadline:
            raise RuntimeCommandError(
                "Reset is still running. Run rag-fresh-start --status; do not resubmit."
            )
        time.sleep(1)
        result = client.request("/wipe")
        if reset_id and result.get("id") != reset_id:
            raise RuntimeCommandError(
                "Reset identity changed. Check the web UI; rebuilding stopped."
            )
    if result["status"] != "succeeded":
        raise RuntimeCommandError(
            "Reset did not complete successfully. Some data may already be deleted. "
            "Run rag-fresh-start --status. Rebuilding was not started."
        )
    completed = result.get("completed", [])
    if not {"database_removed", "runtime_files_removed"}.issubset(completed) or result.get(
        "removed_files", 0
    ) != len(target["files"]):
        raise RuntimeCommandError(
            "Reset completion evidence is missing. Use View reset status; no rebuild attempted."
        )
    print(
        "Verified deleted: project database contents and "
        + str(result.get("removed_files", 0))
        + " previewed runtime files."
    )
    if extreme:
        if (
            result.get("browser_cleared") is not True
            or "extreme_complete" not in completed
            or result.get("removed_volumes", []) != target.get("extra_volumes", [])
        ):
            raise RuntimeCommandError(
                "Extreme completion is unverified; inspect reset status. No restart attempted."
            )
        print("Verified deleted inventory:")
        for item in target["files"]:
            print("  File: " + json.dumps(item["path"]))
        for volume in result.get("removed_volumes", []):
            print("  Volume: " + json.dumps(volume))
        print("Browser DocReview data deleted and acknowledged for: " + result["browser_origin"])
        print(
            "Preserved: tracked files and edits, Git history, unrelated files, host dependencies, "
            "host Ollama and external credentials. Other browser profiles/origins were not cleared."
        )
        print(
            "Services remain stopped. Run rag-quickstart, configure the new .env locally, "
            "then follow the tutorial to prepare data again."
        )
        return 0
    print(
        "Preserved: code/Git, .env/keys, tracked sources, unrelated files and host Ollama. "
        "Browser conversations still require Clear browser data in the reset UI."
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
    print(
        "Build completed and service startup submitted. Server "
        "readiness is not yet verified; run rag-corpus readiness."
    )
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
        path = "/jobs/" if args.kind == "status" else "/corpus/"
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
    reset_parser = commands.add_parser(
        "fresh-start",
        help="Confirm a destructive reset, rebuild, and restart.",
        description="Ordinary mode: "
        + WARNING
        + "\nExtreme mode additionally deletes previewed .env files, custom corpus, caches "
        "and project volumes after two confirmations and browser deletion acknowledgement. "
        "It never restarts services automatically. "
        "Start rag-dev up -d first. --status only reads existing reset evidence.",
    )
    reset_mode = reset_parser.add_mutually_exclusive_group()
    reset_mode.add_argument(
        "--status",
        action="store_true",
        help="Read the last reset status without deleting or restarting anything.",
    )
    reset_mode.add_argument(
        "--extreme",
        action="store_true",
        help=(
            "Delete previewed local configuration/runtime/caches and "
            "acknowledged browser data; two confirmation gates, no "
            "restart."
        ),
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
        return (
            (reset_status(ROOT) if args.status else fresh_start(ROOT, extreme=args.extreme))
            if args.command == "fresh-start"
            else corpus(args, ROOT)
        )
    except (RuntimeCommandError, OperatorLifecycleError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except EOFError, KeyboardInterrupt:
        print(
            "Stopped waiting. For reset evidence run rag-fresh-start --status; "
            "check corpus jobs in the web UI.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
