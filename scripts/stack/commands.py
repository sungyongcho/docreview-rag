"""Share local web reset and corpus operations with the shell commands."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from sqlalchemy.exc import SQLAlchemyError

from scripts.stack.environment import load_local_environment
from scripts.stack.fresh import receipt_path, start_fresh, status as fresh_status
from scripts.stack.operator import LocalOperator, OperatorLifecycleError
from scripts.stack.prompts import SetupCancelledError
from scripts.stack.quickstart import quickstart

ROOT = Path(__file__).resolve().parents[2]
WARNING = """WARNING: Ordinary clean start deletes ORM-owned database data and downloaded sources.
Code, .env, exports, saved model settings, unrelated tables, the DB volume and host Ollama remain.
The exact preview and uppercase Y confirmation are required; no backup is created.
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
                        "Execution may be uncertain. Run rag-reset --status "
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
    host_status = fresh_status(root, "reset") if receipt_path(root, "reset").exists() else None
    print(
        "Operator reset evidence (extreme or web reset); host clean-start status: rag-schema check."
    )
    try:
        result = operator_client(root).request("/wipe")
    except OperatorLifecycleError, RuntimeCommandError:
        if host_status is None:
            raise
        print("Previous web/extreme operator evidence is currently unavailable.")
        return host_status
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
    return host_status if host_status is not None else (0 if status in {"idle", "succeeded"} else 1)


def reset(
    root: Path, *, timeout: float = 1800, keep_sources: bool = False, sample: bool = False
) -> int:
    """Run the narrower host ORM/source reset, preserving volumes and environment files."""
    if not sys.stdin.isatty():
        raise RuntimeCommandError("Run interactively to review the reset; nothing changed.")
    return quickstart(root, reset=True, keep_sources=keep_sources, sample=sample, timeout=timeout)


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
        "reset", help="Reset ORM data and sources; preserve .env and volumes.", description=WARNING
    )
    reset_mode = reset_parser.add_mutually_exclusive_group()
    reset_mode.add_argument(
        "--status", action="store_true", help="Read host and previous web/extreme reset evidence."
    )
    reset_mode.add_argument("--keep-sources", action="store_true")
    reset_mode.add_argument("--sample", action="store_true")
    fresh_parser = commands.add_parser(
        "start-fresh", help="Clean this checkout, then start quick setup."
    )
    fresh_parser.add_argument("--status", action="store_true")
    fresh_parser.add_argument("--extreme", action="store_true")
    fresh_parser.add_argument("--no-start", action="store_true")
    fresh_parser.add_argument("--discard-tracked", action="store_true")
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
    for child in (reset_parser, fresh_parser, jobs):
        child.add_argument("--verbose", "-vv", action="store_true", help="Stream step output.")
    args = parser.parse_args()
    if args.verbose:
        os.environ["DOCREVIEW_VERBOSE"] = "1"
    try:
        if args.command == "start-fresh":
            return (
                fresh_status(ROOT, "start-fresh")
                if args.status
                else start_fresh(
                    ROOT,
                    extreme=args.extreme,
                    no_start=args.no_start,
                    discard_tracked=args.discard_tracked,
                )
            )
        if args.command == "reset":
            return (
                reset_status(ROOT)
                if args.status
                else reset(ROOT, keep_sources=args.keep_sources, sample=args.sample)
            )
        return corpus(args, ROOT)
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
        if args.command == "reset" and not args.status:
            message = (
                "Host clean start interrupted. A reset may be partial: preserve "
                "data/.schema-recreate-journal and run rag-schema check before another preview. "
                "No automatic retry or restart occurs."
            )
        else:
            message = (
                "Stopped waiting. For extreme/web reset evidence run rag-reset --status; "
                "check corpus jobs in the web UI."
            )
        print(message, file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
