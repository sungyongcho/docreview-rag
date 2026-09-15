"""Restore a verified public bundle into isolated local PROD storage without provider calls."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from dotenv import dotenv_values

from deploy.gcp.verify_artifacts import (
    EVALUATIONS,
    digest,
    extract_artifacts,
    validate_artifacts,
    validate_database,
)
from scripts.stack.environment import load_local_environment
from scripts.stack.fresh import docker_inventory, receipt_path, write_receipt


def storage(root: Path) -> Path:
    """Keep restored data under this checkout without following user-owned directory links."""
    target = root / "data" / "local-prod"
    for path in (
        root / "data",
        target,
        *(target / name for name in ("corpus", "eval-runs", "runtime")),
    ):
        if path.is_symlink():
            raise ValueError(f"Local PROD storage must not be a symlink: {path}")
    return target


def ensure_storage(root: Path) -> None:
    """Create only missing mount directories with access for the configured host group."""
    target = storage(root)
    target.mkdir(parents=True, exist_ok=True)
    for name in ("corpus", "eval-runs", "runtime"):
        path = target / name
        if not path.exists():
            path.mkdir(mode=0o770)
            path.chmod(0o770)
        elif not path.is_dir():
            raise ValueError(f"Local PROD mount is not a directory: {path}")


def artifact_directory(root: Path, explicit: Path | None) -> Path:
    """Choose an explicit/configured bundle or the sole saved public bundle, never a download."""
    values = dotenv_values(root / ".env") | dict(os.environ)
    selected = explicit or values.get("DOCREVIEW_PROD_ARTIFACT_DIR")
    if selected:
        path = Path(selected).expanduser()
        return (root / path).resolve() if not path.is_absolute() else path.resolve()
    cache = Path.home() / ".local/share/docreview/prod-artifacts"
    candidates = sorted(path.parent for path in cache.glob("*/checksums.json"))
    if len(candidates) != 1:
        raise ValueError(
            "Specify a saved public bundle with --artifacts PATH or DOCREVIEW_PROD_ARTIFACT_DIR. "
            "No bundle is downloaded and no embeddings are generated automatically."
        )
    return candidates[0].resolve()


def validate_restored_files(bundle: Path, target: Path, manifest: dict) -> None:
    """Check actual mounted source/evaluation bytes, including on a later reuse invocation."""
    if json.loads((target / "corpus/manifest.json").read_text()) != manifest:
        raise ValueError("The restored corpus manifest differs from the selected bundle.")
    checksums = json.loads((bundle / "checksums.json").read_text())
    files = [(target / "corpus" / item["path"], item["sha256"]) for item in manifest["artifacts"]]
    files.extend(
        (target / "eval-runs" / name, checksums[f"eval_runs/{name}"]["sha256"])
        for name in EVALUATIONS
    )
    for path, expected in files:
        if path.is_symlink() or not path.resolve().is_relative_to(target.resolve()):
            raise ValueError(f"Restored file escapes local PROD storage: {path}")
        if digest(path) != expected:
            raise ValueError(f"Restored file checksum mismatch: {path}")


@contextmanager
def preparation_lock(root: Path) -> Iterator[None]:
    """Serialize preparation per checkout without removing another process's lock file."""
    path = receipt_path(root, "prod-prepare").with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another local PROD preparation is running.") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class LocalDatabase:
    """Pin Docker to the verified local daemon and only this checkout's PROD Compose project."""

    def __init__(self, root: Path):
        """Verify local Docker ownership before retaining the command/environment."""
        from scripts.stack.__main__ import compose_command, compose_environment

        self.root = root
        self.docker = docker_inventory(root, extreme=False)["docker"]
        self.command = self.docker + compose_command(root, "prod", [])[1:]
        self.environment = compose_environment(
            "prod", load_local_environment(root / ".env", mode="prod")
        )

    def run(self, *arguments: str, input_file: Path | None = None) -> str:
        """Run one pinned local command and expose a bounded failure rather than a false success."""
        with input_file.open("rb") if input_file else open(os.devnull, "rb") as source:
            result = subprocess.run(
                [*self.command, *arguments],
                cwd=self.root,
                env=self.environment,
                stdin=source,
                capture_output=True,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(
                f"Local PROD command failed ({arguments[0]}, exit {result.returncode}): "
                + result.stderr.decode(errors="replace")[-2000:]
            )
        return result.stdout.decode()

    def sql(self, query: str) -> str:
        """Execute a fixed local database statement; external DATABASE_URL is never read."""
        return self.run(
            "exec",
            "-T",
            "db",
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-U",
            "filing",
            "-d",
            "filing",
            "-c",
            query,
        ).strip()

    def volume(self) -> str | None:
        """Observe the database volume instead of trusting a mode flag or Compose file."""
        identity = self.run("ps", "-q", "db").strip()
        if not identity:
            return None
        details = json.loads(
            subprocess.check_output([*self.docker, "inspect", identity], text=True)
        )[0]
        return next(
            (
                mount.get("Name")
                for mount in details["Mounts"]
                if mount.get("Destination") == "/var/lib/postgresql/data"
            ),
            None,
        )

    def isolated(self) -> bool:
        """Require the exact local PROD volume before restoring any data."""
        return self.volume() == f"{self.root.name}_prod_pg_data"

    def report(self) -> dict:
        """Read the same identity/vector/snapshot checks used for the public deployment."""
        query = (self.root / "deploy/gcp/verify_restore.sql").read_text()
        report = json.loads(self.sql(query))
        if int(
            self.sql(
                "SELECT count(*) FROM chunk_embeddings "
                "WHERE tokenizer <> 'tiktoken:cl100k_base:literal-special:v1'"
            )
        ):
            raise ValueError("Restored embeddings have an incompatible tokenizer identity.")
        return report

    def validate_references(self) -> None:
        """Check every restored foreign key after re-enabling restore-time triggers."""
        from sqlalchemy import func, select
        from sqlalchemy.dialects import postgresql

        from app.db.models import Base

        for table in Base.metadata.sorted_tables:
            for constraint in table.foreign_key_constraints:
                child = table.alias("child")
                parent = constraint.referred_table.alias("parent")
                present = (
                    select(1)
                    .select_from(parent)
                    .where(
                        *(
                            parent.c[element.column.name] == child.c[element.parent.name]
                            for element in constraint.elements
                        )
                    )
                    .correlate(child)
                    .exists()
                )
                query = (
                    select(func.count())
                    .select_from(child)
                    .where(
                        *(child.c[column.name].is_not(None) for column in constraint.columns),
                        ~present,
                    )
                )
                sql = str(
                    query.compile(
                        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                    )
                )
                if int(self.sql(sql)):
                    raise ValueError(
                        f"Restored foreign key is invalid: {table.name}.{constraint.name}"
                    )
        enabled = self.sql(
            "SELECT count(*) FROM pg_trigger WHERE "
            "tgname='docreview_chunks_invalidate_bm25_stats' AND tgenabled='O'"
        )
        if enabled != "1":
            raise ValueError("The BM25 invalidation trigger is not enabled after restore.")


def wait_search_ready(root: Path, *, timeout: float = 90) -> dict:
    """Require actual public API search readiness after a restore, without submitting a question."""
    bindings = load_local_environment(root / ".env", mode="prod")
    url = (
        f"http://{bindings['DOCREVIEW_LOCAL_HOST']}:{bindings['APP_PORT']}/docreview-rag/api/ready/"
    )
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=5) as response:
                latest = (
                    json.load(response)
                    if "application/json" in response.headers.get("Content-Type", "")
                    else {"transport_status": response.status}
                )
            if latest.get("environment") == "prod" and latest.get("status") == "ready":
                return latest
        except HTTPError as error:
            with error:
                latest = (
                    json.load(error)
                    if "application/json" in error.headers.get("Content-Type", "")
                    else {"transport_status": error.code}
                )
        except ConnectionError, TimeoutError, OSError:
            pass
        time.sleep(1)
    raise RuntimeError(f"Local PROD search readiness was not confirmed; last status: {latest}")


def prepare(root: Path, *, artifacts: Path | None = None, check: bool = False) -> int:
    """Validate/reuse a public bundle, or restore it once into empty isolated local storage."""
    from scripts.stack.cli import require_running_mode

    require_running_mode(root, "prod")
    bundle = artifact_directory(root, artifacts)
    print(f"[1/5] Validate saved public bundle: {bundle}", flush=True)
    manifest = validate_artifacts(bundle)
    fingerprint = hashlib.sha256((bundle / "checksums.json").read_bytes()).hexdigest()
    target = storage(root)
    database = LocalDatabase(root)
    receipt = receipt_path(root, "prod-prepare")
    previous = json.loads(receipt.read_text()) if receipt.exists() else {}
    if previous.get("status") == "running":
        raise ValueError(
            "An incomplete local PROD restore is recorded. Preserve it and inspect "
            f"{receipt}; no restore is retried automatically."
        )
    recorded = previous.get("status") in {"succeeded", "failed", "interrupted"}
    if recorded and database.isolated():
        if previous.get("bundle_sha256") != fingerprint:
            raise ValueError(
                "A different PROD bundle is already prepared; no data was overwritten."
            )
        recovering = previous.get("status") != "succeeded"
        try:
            validate_restored_files(bundle, target, manifest)
            report = database.report()
            validate_database(manifest, report, allow_runtime_history=True)
            if recovering:
                database.validate_references()
        except (ValueError, OSError) as error:
            raise ValueError(
                f"Incomplete local PROD data: {error}. No restore is retried automatically."
            ) from error
        wait_search_ready(root)
        if recovering and not check:
            with preparation_lock(root):
                if json.loads(receipt.read_text()) != previous:
                    raise ValueError("Preparation receipt changed during verification.")
                write_receipt(
                    root,
                    "prod-prepare",
                    status="succeeded",
                    bundle_sha256=fingerprint,
                    documents=len(manifest["documents"]),
                    chunks=report["chunks"],
                    embeddings=report["matching_embeddings"],
                    readiness="ready",
                    reconciled=True,
                )
        print("Local PROD data is already prepared and verified; no restore or embedding call.")
        return 0
    if recorded:
        raise ValueError(
            "Recorded local PROD storage is missing; preserve the receipt and inspect it."
        )
    if check:
        print(
            f"Bundle verified: {len(manifest['documents'])} documents. Local PROD is not prepared."
        )
        return 0
    with preparation_lock(root):
        # The receipt and hashes must still match immediately before the first mutation.
        current = json.loads(receipt.read_text()) if receipt.exists() else {}
        if current != previous:
            raise ValueError("Preparation state changed; no data was changed.")
        validate_artifacts(bundle)
        for name in ("corpus", "eval-runs"):
            path = target / name
            if path.exists() and any(path.iterdir()):
                raise ValueError(f"Local PROD restore target is not empty: {path}")
        ensure_storage(root)
        print(
            "[2/5] Stop only the API and prepare the isolated PROD database; keep the web up.",
            flush=True,
        )
        database.run("stop", "app")
        database.run("up", "-d", "--wait", "--wait-timeout", "120", "db")
        if not database.isolated():
            raise ValueError("The running database is not the dedicated local PROD volume.")
        # Run the current image's schema gate; never drop tables or invoke a provider.
        database.run(
            "run",
            "--rm",
            "--no-deps",
            "app",
            "/app/.venv/bin/python",
            "-c",
            "print('Local PROD schema verified.')",
        )
        before = database.report()
        if any(
            before.get(key)
            for key in (
                "documents",
                "chunks",
                "embeddings",
                "snapshots",
                "runs",
                "traces",
                "operator_jobs",
            )
        ):
            raise ValueError("The local PROD database is not empty; existing data was preserved.")
        if database.sql("SELECT rolsuper FROM pg_roles WHERE rolname=current_user") != "t":
            raise ValueError("Restore requires the dedicated local database owner role.")
        write_receipt(root, "prod-prepare", status="running", bundle_sha256=fingerprint)
        try:
            print("[3/5] Restore saved public sources, vectors and evaluation records.", flush=True)
            extract_artifacts(bundle, target)
            database.run(
                "exec",
                "-T",
                "db",
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "--data-only",
                "--disable-triggers",
                "--no-owner",
                "--no-privileges",
                "-U",
                "filing",
                "-d",
                "filing",
                input_file=bundle / "database.public.dump",
            )
            print(
                "[4/5] Verify restored identities, vectors, snapshots and empty private history.",
                flush=True,
            )
            report = database.report()
            validate_database(manifest, report)
            database.validate_references()
            validate_restored_files(bundle, target, manifest)
            print("[5/5] Start the local PROD API and verify actual search readiness.", flush=True)
            database.run("up", "-d", "--no-deps", "app")
            readiness = wait_search_ready(root)
            write_receipt(
                root,
                "prod-prepare",
                status="succeeded",
                bundle_sha256=fingerprint,
                documents=len(manifest["documents"]),
                chunks=report["chunks"],
                embeddings=report["matching_embeddings"],
                readiness=readiness["status"],
            )
        except (Exception, KeyboardInterrupt) as error:
            write_receipt(
                root,
                "prod-prepare",
                status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                bundle_sha256=fingerprint,
                error=type(error).__name__,
            )
            raise
    print("Local PROD is ready for question testing. No embeddings were generated.")
    return 0
