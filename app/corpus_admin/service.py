"""Local corpus administration over real files and PostgreSQL state.

``RuntimeCorpusAdminService`` is the single entry point that the administrator API,
the public portfolio and the release app use. It owns the settings and runtime resources shared by
its operations: ``CorpusInspector`` reads status, snapshots and
documents, ``CorpusOperations`` runs one command, and ``CorpusJobQueue`` queues
commands and runs them one at a time.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.corpus_admin.inspection import CorpusInspector
from app.corpus_admin.job_queue import CorpusJobQueue
from app.corpus_admin.operations import CorpusOperations
from app.corpus_admin.types import AdminCommand, AdminJob, CorpusSnapshot, CorpusStatus
from app.db.session_factory import SessionFactory, default_session_factory
from app.ingestion.sources.deletion import SourceDeletion
from app.observability.redaction import redact_sensitive_text
from app.operator.corpus_access import CorpusAccess
from app.operator.jobs.execution import JobExecutionCoordinator
from app.operator.jobs.store import JobStore
from app.retrieval.embedding.provider import EmbeddingProvider


class RuntimeCorpusAdminService:
    """Local-only corpus administration over real files and PostgreSQL state."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        engine: AsyncEngine | None = None,
        session_factory: SessionFactory = default_session_factory,
        embedding_provider: EmbeddingProvider | None = None,
        job_store: JobStore | None = None,
        corpus_access: CorpusAccess | None = None,
        execution_coordinator: JobExecutionCoordinator | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.corpus_root = self.settings.corpus_dir.resolve()
        self.session_factory = session_factory
        self._engine = engine
        self._embedding_provider = embedding_provider
        # Previews, queued deletions and their execution must share one set of approvals.
        self._source_deletion = SourceDeletion(self.corpus_root)
        self._inspector = CorpusInspector(self)
        self._operations = CorpusOperations(self, self._inspector, self._source_deletion)
        self._job_queue = CorpusJobQueue(
            corpus_root=self.corpus_root,
            source_deletion=self._source_deletion,
            run_operation=self._operations.run,
            redact=self.redact,
            invalidate_status=self._inspector.invalidate_status,
            job_store=job_store or JobStore(session_factory=session_factory),
            corpus_access=corpus_access or CorpusAccess(),
            execution_coordinator=execution_coordinator or JobExecutionCoordinator(),
        )

    @property
    def corpus_access(self) -> CorpusAccess:
        """Return the gate that holds searches off while jobs rewrite search data."""
        return self._job_queue.corpus_access

    async def status(self, *, max_age_s: float = 0.0) -> CorpusStatus:
        """Return the operational status alone, without document rows or file scans.

        ``max_age_s`` lets ``/ready`` reuse a recent reading; ``0.0`` always measures.
        """
        return await self._inspector.status(max_age_s=max_age_s)

    async def snapshot(
        self,
        *,
        registry: str = "",
        issuer: str = "",
        fiscal_year: int | None = None,
        language: str = "",
        parse_status: str = "",
    ) -> CorpusSnapshot:
        """Inspect live state while failing closed on schema drift or database errors."""
        return await self._inspector.snapshot(
            registry=registry,
            issuer=issuer,
            fiscal_year=fiscal_year,
            language=language,
            parse_status=parse_status,
        )

    async def preview_source_deletion(self, document_ids: tuple[str, ...]) -> dict[str, Any]:
        """Read exact deletion targets in a thread without blocking service requests."""
        return await asyncio.to_thread(self._source_deletion.preview, document_ids)

    async def enqueue(self, command: AdminCommand, *, retry_of: str | None = None) -> AdminJob:
        """Queue one operation and start the persistent single worker lazily."""
        return await self._job_queue.enqueue(command, retry_of=retry_of)

    async def retry(self, job_id: str) -> AdminJob:
        """Requeue the command from one failed or interrupted operation only."""
        return await self._job_queue.retry(job_id)

    async def cancel(self, job_id: str) -> AdminJob:
        """Cancel queued work or request cooperative running-job cancellation."""
        return await self._job_queue.cancel(job_id)

    async def recover_jobs(self) -> None:
        """Mark stale process-owned jobs interrupted once before accepting work."""
        await self._job_queue.recover_jobs()

    @property
    def database_engine(self) -> AsyncEngine:
        """Resolve an injected or process engine lazily."""
        if self._engine is None:
            from app.db.session import engine

            self._engine = engine
        return self._engine

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        """Resolve the server-configured embedding provider without accepting UI secrets."""
        if self._embedding_provider is None:
            from app.retrieval.embedding.provider import get_embedding_provider

            self._embedding_provider = get_embedding_provider(self.settings)
        return self._embedding_provider

    def redact(self, text: str) -> str:
        """Remove configured server credentials and recognizable secret syntax.

        Messages from providers and failures can echo a key back, so every message
        shown to the operator passes through here first.
        """
        configured_secrets = (self.settings.openai_api_key, self.settings.dart_api_key)
        secret_values = [
            secret.get_secret_value()
            for secret in configured_secrets
            if secret is not None and secret.get_secret_value()
        ]
        return redact_sensitive_text(text, secret_values=secret_values)
