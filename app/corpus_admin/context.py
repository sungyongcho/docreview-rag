"""Settings, corpus root and live handles shared by the corpus administrator parts.

The inspector, the operations and the job queue all work on one corpus. They share
this object so the embedding provider, which may load a model or build an API
client, is created at most once per service, and so the process database engine is
imported only when a caller actually reaches the database.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings
from app.observability.persistence import redact_sensitive_text
from app.retrieval.embeddings import EmbeddingProvider


def _default_engine() -> AsyncEngine:
    """Resolve the process engine only when live administration needs it."""
    from app.db.session import engine

    return engine


class SessionFactory(Protocol):
    """Build one caller-owned asynchronous database session."""

    def __call__(self) -> AsyncSession:
        """Return one asynchronous session context manager."""
        ...


class CorpusAdminContext:
    """Hold one corpus root and resolve its database engine and embedding provider lazily.

    Parameters
    ----------
    settings : Settings
        Server settings that name the corpus directory, the embedding provider and
        the credentials to keep out of messages.
    engine : AsyncEngine | None
        Engine to use, or ``None`` to use the process engine on first access.
    session_factory : SessionFactory
        Factory for the caller-owned sessions that read and write corpus rows.
    embedding_provider : EmbeddingProvider | None
        Provider to use, or ``None`` to build the configured one on first access.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        engine: AsyncEngine | None,
        session_factory: SessionFactory,
        embedding_provider: EmbeddingProvider | None,
    ) -> None:
        self.settings = settings
        self.corpus_root = settings.corpus_dir.resolve()
        self.session_factory = session_factory
        self._engine = engine
        self._embedding_provider = embedding_provider

    @property
    def database_engine(self) -> AsyncEngine:
        """Resolve an injected or process engine lazily."""
        return self._engine or _default_engine()

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        """Resolve the server-configured embedding provider without accepting UI secrets."""
        if self._embedding_provider is None:
            from app.retrieval.embeddings import get_embedding_provider

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
