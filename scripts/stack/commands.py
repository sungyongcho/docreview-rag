"""Share local web reset and corpus operations with the shell commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from sqlalchemy.exc import SQLAlchemyError

from scripts.stack.environment import load_local_environment
from scripts.stack.operator import LocalOperator, OperatorLifecycleError
from scripts.stack.prompts import SetupCancelledError, step
from scripts.stack.quickstart import quickstart

ROOT = Path(__file__).resolve().parents[2]
WARNING = """WARNING: Ordinary clean start deletes ORM-owned database data and downloaded sources.
Code, .env, exports, saved model settings, unrelated tables, the DB volume and host Ollama remain.
The exact preview and typed confirmation are required; no backup is created.
--keep-sources preserves downloads; --sample presets the sample without downloading.
After a verified reset, DEV starts and readiness is checked before the web tutorial hand-off."""


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
    print(
        "Operator reset evidence (extreme or web reset); host clean-start status: rag-schema check."
    )
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


def fresh_start(
    root: Path,
    *,
    timeout: float = 1800,
    extreme: bool = False,
    keep_sources: bool = False,
    sample: bool = False,
) -> int:
    """Use the guarded host clean start, or retain the explicit extreme reset protocol."""
    if not sys.stdin.isatty():
        print(WARNING if not extreme else "EXTREME RESET: NO BACKUP. IRREVERSIBLE DELETION.")
        raise RuntimeCommandError("Run interactively to review and type the deletion confirmation.")
    if not extreme:
        return quickstart(
            root, reset=True, keep_sources=keep_sources, sample=sample, timeout=timeout
        )
    step(
        1,
        3,
        "Extreme reset preview",
        "Inspect the exact inventory; two confirmations and browser acknowledgement are required.",
    )
    print(
        WARNING
        if not extreme
        else (
            "+==================================================+\n"
            "| EXTREME RESET: NO BACKUP. IRREVERSIBLE DELETION.  |\n"
            "+==================================================+\n"
            "Deletes project .env files, untracked runtime/custom corpus and build caches, "
            "project volumes, and DocReview data in the browser that acknowledges this reset.\n"
            "Preserves tracked files and edits, Git history, unrelated files, host Ollama "
            "and external credentials. No automatic restart."
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
    step(
        2,
        3,
        "Confirmed deletion",
        "Submit the preview once; inspect progress without retrying deletion.",
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
        step(
            3,
            3,
            "Deletion report",
            "Check the completed inventory before starting fresh guided setup.",
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
    parser = argparse.ArgumentParser(description=__doc__, color=False)
    commands = parser.add_subparsers(dest="command", required=True)
    reset_parser = commands.add_parser(
        "fresh-start",
        help="Confirm a destructive reset, rebuild, and restart.",
        description="Ordinary mode: "
        + WARNING
        + "\nExtreme mode additionally deletes previewed .env files, custom corpus, caches "
        "and project volumes after two confirmations and browser deletion acknowledgement. "
        "It never restarts services automatically. "
        "Only extreme mode requires an existing rag-dev operator. "
        "--status reads extreme/web reset evidence; use rag-schema check for host schema state.",
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
    reset_mode.add_argument(
        "--keep-sources",
        action="store_true",
        help="Reset ORM data while keeping downloaded sources.",
    )
    reset_mode.add_argument(
        "--sample",
        action="store_true",
        help="Reset ORM data and sources, then preset the sample selection without downloading.",
    )
    jobs = commands.add_parser(
        "corpus",
        help="Use the same corpus jobs as the development web UI.",
        description=(
            "Use the same corpus jobs as the development web Build and Jobs panels. "
            "inspect lists manifests, documents and index readiness; readiness reads runtime "
            "and model configuration; status checks job completion before the next step. "
            "Downloads require SEC/DART configuration; embeddings may incur provider charges. "
            "After reset, download sources again, ingest the selected manifest, then rebuild "
            "embeddings and BM25 statistics as separate operations. ingest_manifest only "
            "parses and stores chunks; rebuild_bm25 computes the lexical index. "
            "Configure the answer model and evaluate "
            "in the web UI. "
            "Public read-only deployments cannot perform admin operations."
        ),
        epilog="Example: rag-corpus acquire_edgar --identifier NVDA --year 2024",
    )
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
            (
                reset_status(ROOT)
                if args.status
                else fresh_start(
                    ROOT, extreme=args.extreme, keep_sources=args.keep_sources, sample=args.sample
                )
            )
            if args.command == "fresh-start"
            else corpus(args, ROOT)
        )
    except SetupCancelledError as error:
        print(str(error))
        return 0
    except SQLAlchemyError as error:
        print(
            f"Local database work failed ({type(error).__name__}). "
            "The reset outcome may be partial or uncertain. Preserve data/.schema-recreate-journal "
            "and run rag-schema check before requesting another preview; no deletion is retried.",
            file=sys.stderr,
        )
        return 1
    except (
        RuntimeCommandError,
        OperatorLifecycleError,
        ValueError,
        RuntimeError,
        OSError,
        subprocess.CalledProcessError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    except EOFError, KeyboardInterrupt:
        if args.command == "fresh-start" and not args.extreme and not args.status:
            message = (
                "Host clean start interrupted. A reset may be partial: preserve "
                "data/.schema-recreate-journal and run rag-schema check before another preview. "
                "No automatic retry or restart occurs."
            )
        else:
            message = (
                "Stopped waiting. For extreme/web reset evidence run rag-fresh-start --status; "
                "check corpus jobs in the web UI."
            )
        print(message, file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
