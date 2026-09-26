"""Local corpus administration over real files and PostgreSQL state.

``RuntimeCorpusAdminService`` is the single entry point that the administrator API,
the public portfolio and the release app use. It builds the parts over one shared
context and delegates to them: ``CorpusInspector`` reads status, snapshots and
documents, ``CorpusOperations`` runs one command, and ``CorpusJobQueue`` queues
commands and runs them one at a time.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.corpus_admin.context import CorpusAdminContext
from app.corpus_admin.inspection import CorpusInspector
from app.corpus_admin.job_queue import CorpusJobQueue
from app.corpus_admin.operations import CorpusOperations, OperationRunner
from app.corpus_admin.types import (
    AdminCommand,
    AdminJob,
    CorpusSnapshot,
    CorpusStatus,
    DocumentDetail,
)
from app.db.session_factory import SessionFactory
from app.ingestion.source_deletion import SourceDeletion
from app.operator.corpus_access import CorpusAccess
from app.operator.jobs import JobExecutionCoordinator, JobStore, _default_session_factory
from app.retrieval.embeddings import EmbeddingProvider


class RuntimeCorpusAdminService:
    """Local-only corpus administration over real files and PostgreSQL state."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        engine: AsyncEngine | None = None,
        session_factory: SessionFactory = _default_session_factory,
        embedding_provider: EmbeddingProvider | None = None,
        operation_runner: OperationRunner | None = None,
        job_store: JobStore | None = None,
        corpus_access: CorpusAccess | None = None,
        execution_lock: asyncio.Lock | None = None,
        execution_coordinator: JobExecutionCoordinator | None = None,
    ) -> None:
        context = CorpusAdminContext(
            settings or get_settings(),
            engine=engine,
            session_factory=session_factory,
            embedding_provider=embedding_provider,
        )
        # Previews, queued deletions and their execution must share one set of approvals.
        self._source_deletion = SourceDeletion(context.corpus_root)
        self._inspector = CorpusInspector(context)
        self._operations = CorpusOperations(
            context, self._inspector, self._source_deletion, operation_runner
        )
        self._job_queue = CorpusJobQueue(
            corpus_root=context.corpus_root,
            source_deletion=self._source_deletion,
            run_operation=self._operations.run,
            redact=context.redact,
            invalidate_status=self._inspector.invalidate_status,
            job_store=job_store,
            corpus_access=corpus_access or CorpusAccess(),
            execution_lock=execution_lock or asyncio.Lock(),
            execution_coordinator=execution_coordinator or JobExecutionCoordinator(),
        )

    @property
    def corpus_access(self) -> CorpusAccess:
        """Return the gate that holds searches off while jobs rewrite search data."""
        return self._job_queue.corpus_access

    @corpus_access.setter
    def corpus_access(self, corpus_access: CorpusAccess) -> None:
        """Share another gate, such as the one the API's searches already use."""
        self._job_queue.corpus_access = corpus_access

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

    async def document_detail(self, doc_id: str) -> DocumentDetail | None:
        """Load one live document and no more than five bounded chunk bodies."""
        return await self._inspector.document_detail(doc_id)

    async def preview_source_deletion(self, document_ids: tuple[str, ...]) -> dict[str, Any]:
        """Read exact deletion targets in a thread without blocking service requests."""
        return await asyncio.to_thread(self._source_deletion.preview, document_ids)

    async def enqueue(self, command: AdminCommand, *, retry_of: str | None = None) -> AdminJob:
        """Queue one operation and start the persistent single worker lazily."""
        return await self._job_queue.enqueue(command, retry_of=retry_of)

    def forget_history(self, job_ids: tuple[str, ...]) -> None:
        """Release terminal cache records only after their persistent deletion."""
        self._job_queue.forget_history(job_ids)

    async def retry(self, job_id: str) -> AdminJob:
        """Requeue the command from one failed or interrupted operation only."""
        return await self._job_queue.retry(job_id)

    async def cancel(self, job_id: str) -> AdminJob:
        """Cancel queued work or request cooperative running-job cancellation."""
        return await self._job_queue.cancel(job_id)

    async def recover_jobs(self) -> None:
        """Mark stale process-owned jobs interrupted once before accepting work."""
        await self._job_queue.recover_jobs()
