"""Preview and execute exact, expiring deletion approvals for current originals."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import secrets
from threading import Lock
import time
from typing import Any

from app.ingestion.acquisition import read_catalog
from app.ingestion.manifest import Manifest
from app.ingestion.source_publication import fixed_path
from app.ingestion.source_storage import commit_sources, confined_path, fingerprint, source_lock


@dataclass
class DeletionApproval:
    """Retain one process-local approval; persisted jobs cannot replay its authority."""

    document_ids: tuple[str, ...]
    fingerprint: str
    expires_at: float
    reserved: bool = False


class SourceDeletion:
    """Bind previews to exact catalog, file and retained-input revisions."""

    def __init__(self, root: Path) -> None:
        """Keep a bounded set of single-use confirmations for this service lifetime."""
        self.root = root
        self._approvals: dict[str, DeletionApproval] = {}
        self._approval_lock = Lock()

    def _plan(
        self, document_ids: tuple[str, ...]
    ) -> tuple[dict[str, Any], Manifest, dict[str, bytes | None], str]:
        """Read exact targets and retained references without changing source data."""
        catalog = read_catalog(self.root / "manifest.json")
        wanted = set(document_ids)
        if not wanted or len(wanted) != len(document_ids) or len(wanted) > 200:
            raise ValueError("Choose between 1 and 200 unique original documents.")
        documents = [d for d in catalog.documents if d.document_id in wanted]
        if len(documents) != len(wanted):
            raise ValueError("Selected originals changed; refresh the deletion preview.")
        targets = [
            a
            for a in catalog.artifacts
            if a.document_id in wanted and a.role in {"primary", "archive"}
        ]
        references = set(a.path for a in catalog.artifacts if a not in targets)
        retained_inputs = 0
        evidence = {"manifest.json": fingerprint(self.root / "manifest.json")}
        for path in sorted(self.root.glob("*-manifest.json")):
            confined_path(self.root, path.name)
            other = Manifest.read(path)
            references.update(a.path for a in other.artifacts)
            retained_inputs += sum(a.document_id in wanted for a in other.artifacts)
            evidence[path.name] = fingerprint(path)
        by_id = {document.document_id: document for document in documents}
        files = []
        changes: dict[str, bytes | None] = {}
        for artifact in sorted(targets, key=lambda a: a.path):
            document = by_id[artifact.document_id]
            if artifact.path != fixed_path(document.registry, document.filing_id, artifact.role):
                raise ValueError(
                    "Unsupported current source path; legacy files require explicit cleanup."
                )
            path = confined_path(self.root, artifact.path)
            evidence[artifact.path] = fingerprint(path)
            if path.exists():
                retained = artifact.path in references
                files.append(
                    {
                        "path": artifact.path,
                        "byte_length": path.stat().st_size,
                        "retained": retained,
                    }
                )
                if not retained:
                    changes[artifact.path] = None
        removed = {a.artifact_id for a in targets}
        selections = []
        for selection in catalog.selections:
            identities = tuple(i for i in selection.artifact_ids if i not in removed)
            if identities:
                selections.append(selection.model_copy(update={"artifact_ids": identities}))
        updated = Manifest(
            corpus=catalog.corpus,
            documents=catalog.documents,
            artifacts=tuple(a for a in catalog.artifacts if a.artifact_id not in removed),
            selections=tuple(selections),
        )
        plan = {
            "documents": [
                {
                    "document_id": d.document_id,
                    "registry": d.registry,
                    "issuer": d.issuer,
                    "fiscal_year": d.fiscal_year,
                    "filing_id": d.filing_id,
                }
                for d in documents
            ],
            "files": files,
            "retained_inputs": retained_inputs,
            "retained_derived": True,
        }
        digest = hashlib.sha256(json.dumps([plan, evidence], sort_keys=True).encode()).hexdigest()
        return plan, updated, changes, digest

    def preview(self, document_ids: tuple[str, ...]) -> dict[str, Any]:
        """Issue a short-lived confirmation after reading exact files and preserved inputs."""
        with source_lock(self.root):
            plan, _, _, digest = self._plan(document_ids)
        with self._approval_lock:
            now = time.time()
            self._approvals = {k: v for k, v in self._approvals.items() if v.expires_at > now}
            if len(self._approvals) >= 128:
                raise ValueError("Too many deletion previews; wait for earlier previews to expire.")
            token = secrets.token_urlsafe(32)
            expiry = now + 300
            self._approvals[token] = DeletionApproval(document_ids, digest, expiry)
            return {**plan, "token": token, "expires_at": expiry}

    def reserve(self, token: str) -> None:
        """Consume confirmation once before placing its exact targets on the queue."""
        with self._approval_lock:
            approval = self._approvals.get(token)
            if approval is None or approval.reserved or approval.expires_at <= time.time():
                raise ValueError(
                    "Deletion preview expired or was already used; review a new preview."
                )
            approval.reserved = True

    def execute(self, token: str) -> str:
        """Recheck approved revisions and atomically remove only current source registrations."""
        with self._approval_lock:
            approval = self._approvals.pop(token, None)
        if approval is None or not approval.reserved or approval.expires_at <= time.time():
            raise ValueError("Deletion confirmation is no longer valid; review a new preview.")
        with source_lock(self.root):
            plan, catalog, changes, digest = self._plan(approval.document_ids)
            if digest != approval.fingerprint:
                raise ValueError("Sources changed after preview; review the exact files again.")
            commit_sources(self.root, catalog, changes)
        return (
            f"Deleted {len(changes)} current original file(s); cleared "
            f"{len(approval.document_ids)} source registration(s). "
            f"Retained {plan['retained_inputs']} past input(s) and all database/derived data."
        )
