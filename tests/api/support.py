"""Resource doubles for exercising the API runtime without a database."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

from app.api.dependencies import AdminDependencies
from app.corpus_admin.types import AdminCommand, AdminJob


class MemorySession:
    """Track transaction lifetimes; unexpected database operations fail naturally."""

    def __init__(self):
        """Start without an active transaction or rollback."""
        self.transaction_open = False
        self.rollbacks = 0

    async def __aenter__(self):
        """Expose the same session for the runtime's request lifetime."""
        return self

    async def __aexit__(self, error_type, error, traceback):
        """End the request without suppressing failures."""

    def in_transaction(self):
        """Report whether retrieval or persistence holds a transaction."""
        return self.transaction_open

    async def rollback(self):
        """Release a retrieval transaction before the runtime calls a provider."""
        self.rollbacks += 1
        self.transaction_open = False

    @asynccontextmanager
    async def begin(self):
        """Hold the persistence transaction until its caller exits."""
        self.transaction_open = True
        try:
            yield self
        finally:
            self.transaction_open = False


def write_scope_manifest(root, documents):
    """Write request-routing metadata through the same manifest contract as acquisition."""
    from app.ingestion.sources.models import CorpusIdentity, Manifest

    Manifest(
        corpus=CorpusIdentity(corpus_id="routing-test", name="Routing test"),
        documents=tuple(documents),
    ).write(root / "manifest.json")
    return root


def _admin(**owners: object) -> AdminDependencies:
    """Supply only the domain services exercised by one route scenario."""
    return cast(AdminDependencies, SimpleNamespace(**owners))


def _corpus_job(request: AdminCommand, job_id: str = "corpus-1") -> AdminJob:
    """Return a real queued command snapshot without scheduling execution."""
    return AdminJob(job_id, request, "queued", "queued", 0, None, "Queued")
