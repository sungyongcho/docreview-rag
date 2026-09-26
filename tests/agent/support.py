"""Builders shared by the agent tests."""

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.provider import ProviderTurn


def turn(**changes):
    """Build one provider turn with optional field replacements."""
    values = {
        "output_text": "",
        "tool_calls": (),
        "input_tokens": 10,
        "output_tokens": 5,
    }
    values.update(changes)
    return ProviderTurn(**values)


class FakeSession:
    """Duck-typed async session capturing chunk lookups and its own lifecycle."""

    def __init__(self, chunk=None):
        self.chunk = chunk
        self.requested_ids = []
        self.transaction_open = False
        self.rollback_count = 0
        self.closed = False

    async def __aenter__(self):
        """Enter the session context the way an AsyncSession does."""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Roll back any open read transaction and close, mirroring AsyncSession."""
        if self.transaction_open:
            await self.rollback()
        self.closed = True

    async def get(self, model, chunk_id):
        """Record the requested chunk id and return the staged row."""
        del model
        self.requested_ids.append(chunk_id)
        self.transaction_open = True
        return self.chunk

    def in_transaction(self):
        """Report whether this fake session currently holds a transaction."""
        return self.transaction_open

    async def rollback(self):
        """Close the transaction and count the rollback."""
        self.transaction_open = False
        self.rollback_count += 1


class FakeSessionFactory:
    """Session factory recording every session it hands out."""

    def __init__(self, chunk=None):
        self.chunk = chunk
        self.sessions = []

    def __call__(self) -> AsyncSession:
        """Produce one fresh fake session per call, the way a sessionmaker does."""
        session = FakeSession(self.chunk)
        self.sessions.append(session)
        # The duck-typed fake stands in for the AsyncSession a SessionFactory returns.
        return cast(AsyncSession, session)
