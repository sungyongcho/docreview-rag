"""Resource doubles for exercising the API runtime without a database."""

from contextlib import asynccontextmanager


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
