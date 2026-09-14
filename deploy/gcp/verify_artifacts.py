"""Validate and restore only the approved public portfolio artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

EVALUATIONS = (
    "20260909T185659Z-admin-dart-ko.json",
    "20260909T210412Z-admin-dart-en.json",
    "20260909T212413Z-admin-dart-ko.json",
    "20260909T212448Z-admin-dart-ko.json",
)
PUBLIC_FILES = ("database.public.dump", "originals.tar.gz") + tuple(
    f"eval_runs/{name}" for name in EVALUATIONS
)


def digest(path: Path) -> str:
    """Hash a file without loading the database dump into memory."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def validate_artifacts(root: Path) -> dict:
    """Check transfer hashes, archive safety, source identity and evaluation payloads."""
    checksums = json.loads((root / "checksums.json").read_text())
    for name in PUBLIC_FILES:
        path = root / name
        expected = checksums[name]
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != expected["bytes"]
            or digest(path) != expected["sha256"]
        ):
            raise ValueError(f"Artifact checksum mismatch: {name}")
    with tarfile.open(root / "originals.tar.gz") as archive:
        members = archive.getmembers()
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or path.parts[0] != "corpus"
                or str(path) != member.name
                or member.name in names
            ):
                raise ValueError(f"Unsafe or duplicate archive entry: {member.name}")
            names.add(member.name)
        manifest = json.load(archive.extractfile("corpus/manifest.json"))
        expected_scope = {
            (issuer, year)
            for issuer, years in (
                ("NVDA", range(2019, 2025)),
                ("AMD", range(2019, 2025)),
                ("005930", range(2022, 2025)),
                ("000660", range(2022, 2025)),
            )
            for year in years
        }
        documents = manifest["documents"]
        if (
            len(documents) != 18
            or {(row["issuer"], row["fiscal_year"]) for row in documents} != expected_scope
        ):
            raise ValueError("The public portfolio must contain exactly the approved 18 filings")
        document_ids = {row["document_id"] for row in documents}
        primary_documents = {
            row["document_id"] for row in manifest["artifacts"] if row["role"] == "primary"
        }
        if primary_documents != document_ids:
            raise ValueError("Every portfolio document requires its original primary source")
        expected_names = {"corpus/manifest.json"}
        for artifact in manifest["artifacts"]:
            if artifact["document_id"] not in document_ids:
                raise ValueError("The archive contains a source outside the public portfolio")
            name = f"corpus/{artifact['path']}"
            expected_names.add(name)
            with archive.extractfile(name) as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            if (
                actual != artifact["sha256"]
                or archive.getmember(name).size != artifact["byte_length"]
            ):
                raise ValueError(f"Source integrity mismatch: {name}")
        if names != expected_names:
            raise ValueError("The source archive contains unlisted or missing files")
    for name in EVALUATIONS:
        payload = json.loads((root / "eval_runs" / name).read_text())
        if not payload.get("cases") or not payload.get("metrics"):
            raise ValueError(f"Missing evaluation evidence: {name}")
    return manifest


def extract_artifacts(root: Path, destination: Path) -> None:
    """Write validated files exclusively; never replace existing target content."""
    for name in ("corpus", "eval-runs"):
        target = destination / name
        if target.is_symlink() or (target.exists() and any(target.iterdir())):
            raise ValueError(f"Restore target is not empty: {target}")
        target.mkdir(mode=0o750, exist_ok=True)
    with tarfile.open(root / "originals.tar.gz") as archive:
        for member in archive.getmembers():
            target = destination / member.name
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o640)
    for name in EVALUATIONS:
        target = destination / "eval-runs" / name
        with (root / "eval_runs" / name).open("rb") as source, target.open("xb") as output:
            shutil.copyfileobj(source, output)
        target.chmod(0o640)


def validate_database(manifest: dict, report: dict, *, allow_runtime_history: bool = False) -> None:
    """Compare restored database identity, vectors, snapshots and history to the bundle."""
    expected_ids = sorted(row["document_id"] for row in manifest["documents"])
    expected_paths = sorted(f"/app/data/eval_runs/{name}" for name in EVALUATIONS)
    if report["documents"] != expected_ids:
        raise ValueError("Restored document identities differ from the source manifest")
    if report["chunks"] != 10586 or report["matching_embeddings"] != 10586:
        raise ValueError("Expected 10,586 chunks and matching OpenAI 384-dimensional vectors")
    if report["embeddings"] != 10586:
        raise ValueError("Unexpected embeddings exist in the restored database")
    if (
        report["snapshots"] != 4
        or report["public_ready_snapshots"] != 4
        or report["complete_snapshot_documents"] != 4
        or report["evaluation_paths"] != expected_paths
        or report["linked_evaluations"] != 4
    ):
        raise ValueError("Expected four public snapshots linked to the four evaluation files")
    if not allow_runtime_history and any(
        report[name] for name in ("runs", "traces", "operator_jobs")
    ):
        raise ValueError("The public bundle must not contain private runtime history")


def main() -> None:
    """Validate the selected bundle before an optional first-install extraction."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--list-files", action="store_true")
    parser.add_argument("--extract-to", type=Path)
    parser.add_argument("--database-report", type=Path)
    args = parser.parse_args()
    manifest = validate_artifacts(args.artifact_dir)
    if args.database_report:
        validate_database(manifest, json.loads(args.database_report.read_text()))
    if args.extract_to:
        extract_artifacts(args.artifact_dir, args.extract_to)
    if args.list_files:
        print("\n".join(("checksums.json", *PUBLIC_FILES)))
    else:
        print("Public portfolio artifacts verified.")


if __name__ == "__main__":
    main()
