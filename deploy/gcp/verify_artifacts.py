"""Validate and restore only the approved public portfolio artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
from typing import IO


@dataclass(frozen=True)
class PublicBundle:
    """Validated portfolio sources and the exact public files selected for restoration."""

    root: Path
    manifest: dict
    checksums: dict[str, dict]
    evaluations: dict[str, dict]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys just as the application's evaluation reader does."""
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON key in public artifact: {name}")
        result[name] = value
    return result


def _public_checksums(root: Path) -> dict[str, dict]:
    """Select four confined current artifact paths while excluding private bundle files."""
    checksums = json.loads((root / "checksums.json").read_text(), object_pairs_hook=_unique_object)
    evaluations = sorted(name for name in checksums if name.startswith("eval_runs/"))
    if len(evaluations) != 4 or any(
        re.fullmatch(r"eval_runs/[0-9]{8}T[0-9]{6}Z-[a-z0-9]+(?:-[a-z0-9]+)*\.json", name) is None
        for name in evaluations
    ):
        raise ValueError("The public bundle requires exactly four timestamped evaluation files")
    return {
        name: checksums[name] for name in ("database.public.dump", "originals.tar.gz", *evaluations)
    }


def _validate_evaluation(path: Path) -> dict:
    """Require current scoring metadata and the exact source-bound evaluated case identity."""
    payload = json.loads(path.read_text(), object_pairs_hook=_unique_object)
    cases = payload.get("cases")
    metrics = payload.get("metrics")
    config = payload.get("config")
    if (
        not isinstance(cases, list)
        or not cases
        or not isinstance(metrics, dict)
        or not isinstance(config, dict)
    ):
        raise ValueError(f"Missing evaluation evidence: {path.name}")
    golden: list[dict] = []
    identities: set[str] = set()
    for row in cases:
        case = row.get("golden") if isinstance(row, dict) else None
        if not isinstance(case, dict):
            raise ValueError(f"Missing evaluated golden case: {path.name}")
        identity = case.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity in identities:
            raise ValueError(f"Invalid evaluated case identity: {path.name}")
        golden.append(case)
        identities.add(identity)
    encoded = json.dumps(
        sorted(golden, key=lambda case: case["id"]),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    if config.get("evaluated_golden_sha256") != hashlib.sha256(encoded).hexdigest():
        raise ValueError(f"Evaluated golden identity mismatch: {path.name}")
    k = metrics.get("k")
    if type(k) is not int or k <= 0 or config.get("scoring") != {"k": k, "coverage_threshold": 0.5}:
        raise ValueError(f"Missing or inconsistent current scoring settings: {path.name}")
    identity = config.get("admin_identity")
    original_digest = identity.get("golden_sha256") if isinstance(identity, dict) else None
    if (
        not isinstance(original_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", original_digest) is None
    ):
        raise ValueError(f"Missing original golden provenance: {path.name}")
    if not isinstance(payload.get("suite"), str) or not payload["suite"].strip():
        raise ValueError(f"Missing evaluation suite: {path.name}")
    return payload


def digest(path: Path) -> str:
    """Hash a file without loading the database dump into memory."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _member_file(archive: tarfile.TarFile, member: str | tarfile.TarInfo) -> IO[bytes]:
    """Open one regular archive member, refusing entries that have no file content."""
    source = archive.extractfile(member)
    if source is None:
        name = member if isinstance(member, str) else member.name
        raise ValueError(f"Archive entry is not a regular file: {name}")
    return source


def _sha256(source: IO[bytes]) -> str:
    """Hash a stream in bounded chunks."""
    digest = hashlib.sha256()
    while chunk := source.read(1 << 20):
        digest.update(chunk)
    return digest.hexdigest()


def validate_artifacts(root: Path) -> PublicBundle:
    """Check transfer hashes, archive safety, source identity and evaluation payloads."""
    checksums = _public_checksums(root)
    for name, expected in checksums.items():
        path = root / name
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(root.resolve())
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
        with _member_file(archive, "corpus/manifest.json") as manifest_file:
            manifest = json.load(manifest_file)
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
            with _member_file(archive, name) as source:
                actual = _sha256(source)
            if (
                actual != artifact["sha256"]
                or archive.getmember(name).size != artifact["byte_length"]
            ):
                raise ValueError(f"Source integrity mismatch: {name}")
        if names != expected_names:
            raise ValueError("The source archive contains unlisted or missing files")
    evaluations = {
        name.removeprefix("eval_runs/"): _validate_evaluation(root / name)
        for name in checksums
        if name.startswith("eval_runs/")
    }
    return PublicBundle(root, manifest, checksums, evaluations)


def extract_artifacts(bundle: PublicBundle, destination: Path) -> None:
    """Write validated files exclusively; never replace existing target content."""
    for name in ("corpus", "eval-runs"):
        target = destination / name
        if target.is_symlink() or (target.exists() and any(target.iterdir())):
            raise ValueError(f"Restore target is not empty: {target}")
        target.mkdir(mode=0o750, exist_ok=True)
    with tarfile.open(bundle.root / "originals.tar.gz") as archive:
        for member in archive.getmembers():
            target = destination / member.name
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            with _member_file(archive, member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o640)
    for name in bundle.evaluations:
        target = destination / "eval-runs" / name
        with (bundle.root / "eval_runs" / name).open("rb") as source, target.open("xb") as output:
            shutil.copyfileobj(source, output)
        target.chmod(0o640)


def validate_database(
    bundle: PublicBundle, report: dict, *, allow_runtime_history: bool = False
) -> None:
    """Compare restored database identity, vectors, snapshots and history to the bundle."""
    expected_ids = sorted(row["document_id"] for row in bundle.manifest["documents"])
    expected_paths = sorted(f"/app/data/eval_runs/{name}" for name in bundle.evaluations)
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
    evaluations = report["evaluations"]
    if len(evaluations) != 4 or sorted(row["path"] for row in evaluations) != expected_paths:
        raise ValueError("Restored evaluation evidence does not match the bundle")
    for row in evaluations:
        payload = bundle.evaluations[PurePosixPath(row["path"]).name]
        metrics = {
            key: value
            for key, value in payload["metrics"].items()
            if key not in {"k", "scored_case_count"}
        }
        if (
            row["suite"] != payload["suite"]
            or row["config"] != payload["config"]
            or row["metrics"] != metrics
        ):
            raise ValueError("Restored evaluation settings or metrics differ from the artifact")
        sources = {
            (source["doc_id"], source["source_sha256"]) for source in row["snapshot_sources"]
        }
        if any(
            (answer["doc_id"], answer["source_sha256"]) not in sources
            for case in payload["cases"]
            for answer in case["golden"]["answers"]
        ):
            raise ValueError("Evaluated golden sources are missing from the published snapshot")
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
    bundle = validate_artifacts(args.artifact_dir)
    if args.database_report:
        validate_database(bundle, json.loads(args.database_report.read_text()))
    if args.extract_to:
        extract_artifacts(bundle, args.extract_to)
    if args.list_files:
        print("\n".join(("checksums.json", *bundle.checksums)))
    else:
        print("Public portfolio artifacts verified.")


if __name__ == "__main__":
    main()
