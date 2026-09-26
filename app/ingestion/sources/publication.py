"""Publish one current source per official filing identity without losing job inputs."""

from collections.abc import Sequence
import hashlib
from pathlib import Path

from app.ingestion.sources.catalog import read_catalog
from app.ingestion.sources.models import AcquiredFiling, Manifest, ProcessingSelection
from app.ingestion.sources.storage import (
    commit_sources,
    confined_path,
    external_references,
    fingerprint,
    fixed_path,
    source_lock,
)


def publish_acquired(
    path: Path,
    acquired: Sequence[AcquiredFiling],
    *,
    selection_id: str,
    selected_document_ids: Sequence[str],
) -> Manifest:
    """Merge against the latest catalog while holding the cross-process source lock."""
    from app.ingestion.sources.selection import SourceDownloadRequiredError, resolve_primary

    root = path.parent
    with source_lock(root, recover=True):
        catalog = read_catalog(path)
        documents = {d.document_id: d for d in catalog.documents}
        artifacts = {a.artifact_id: a for a in catalog.artifacts}
        remap: dict[str, str] = {}
        document_remap: dict[str, str] = {}
        changes: dict[str, bytes | None] = {}
        references = external_references(root)
        for filing in acquired:
            identity = (filing.document.registry, filing.document.filing_id)
            known = next(
                (d for d in documents.values() if (d.registry, d.filing_id) == identity), None
            )
            document = known or filing.document
            document_remap[filing.document.document_id] = document.document_id
            if (
                document.document_id in documents
                and documents[document.document_id].filing_id != document.filing_id
            ):
                raise ValueError("Document ID belongs to a different filing; refusing replacement.")
            old = [
                a
                for a in artifacts.values()
                if a.document_id == document.document_id and a.role in {"primary", "archive"}
            ]
            if known is not None:
                try:
                    resolve_primary(catalog, document.document_id, root)
                except SourceDownloadRequiredError:
                    pass
            documents[document.document_id] = document
            replacements = []
            for index, artifact in enumerate(filing.artifacts):
                relative = fixed_path(
                    document.registry, document.issuer, document.filing_id, artifact.role
                )
                if artifact.path != relative:
                    raise ValueError(
                        "Unsupported current source path; acquire the filing at its fixed path."
                    )
                payload = filing.payloads[index]
                if (
                    len(payload) != artifact.byte_length
                    or hashlib.sha256(payload).hexdigest() != artifact.sha256
                ):
                    raise ValueError("Downloaded bytes disagree with their acquisition record.")
                if artifact.encoding is not None:
                    payload.decode(artifact.encoding, errors="strict")
                destination = confined_path(root, relative)
                if relative in references and fingerprint(destination) not in {
                    None,
                    artifact.sha256,
                }:
                    raise ValueError(
                        "A past input references the current path; preserve it before replacement."
                    )
                if (
                    destination.exists()
                    and relative not in {a.path for a in old}
                    and fingerprint(destination) != artifact.sha256
                ):
                    raise ValueError(
                        "Unregistered bytes occupy the fixed source path; "
                        "inspect them before acquisition."
                    )
                updated = artifact.model_copy(
                    update={
                        "document_id": document.document_id,
                        "artifact_id": f"{document.document_id}:{artifact.role}:{artifact.sha256}",
                        "path": relative,
                    }
                )
                replacements.append(updated)
                changes[relative] = payload
            primary = next(a for a in replacements if a.role == "primary")
            for artifact in old:
                artifacts.pop(artifact.artifact_id)
                if artifact.role == "primary":
                    remap[artifact.artifact_id] = primary.artifact_id
            artifacts.update((a.artifact_id, a) for a in replacements)
        selections = []
        for selection in catalog.selections:
            if selection.selection_id != selection_id:
                selections.append(
                    selection.model_copy(
                        update={
                            "artifact_ids": tuple(
                                dict.fromkeys(remap.get(i, i) for i in selection.artifact_ids)
                            )
                        }
                    )
                )
        wanted = set(selected_document_ids)
        wanted.update(f.document.document_id for f in acquired)
        wanted = {document_remap.get(identity, identity) for identity in wanted}
        chosen = []
        for document_id in sorted(wanted):
            new_primary = next(
                (
                    a
                    for a in artifacts.values()
                    if a.document_id == document_id and a.role == "primary" and a.path in changes
                ),
                None,
            )
            if new_primary is not None:
                chosen.append(new_primary.artifact_id)
            elif document_id in documents:
                try:
                    chosen.append(resolve_primary(catalog, document_id, root).artifact_id)
                except SourceDownloadRequiredError:
                    pass
        if chosen:
            selections.append(
                ProcessingSelection(selection_id=selection_id, artifact_ids=tuple(chosen))
            )
        result = Manifest(
            corpus=catalog.corpus,
            documents=tuple(documents.values()),
            artifacts=tuple(artifacts.values()),
            selections=tuple(selections),
        )
        commit_sources(root, result, changes)
        return result
