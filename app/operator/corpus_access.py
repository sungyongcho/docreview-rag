"""Coordinate searches with corpus jobs in the single-process local runtime."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class CorpusUpdatingError(Exception):
    """A new search arrived while a corpus writer was waiting or running."""


class JobCancelledError(RuntimeError):
    """Signal cooperative cancellation at one safe progress boundary."""


class CorpusAccess:
    """Drain existing readers before writing and reject new readers without queuing them."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writers = 0
        self._writer_lock = asyncio.Lock()

    @property
    def updating(self) -> bool:
        """Include the draining interval so new readers cannot starve a writer."""
        return self._writers > 0

    @asynccontextmanager
    async def search(self) -> AsyncIterator[None]:
        """Admit one request until all of its retrieval and answer work finishes."""
        async with self._condition:
            if self.updating:
                raise CorpusUpdatingError(
                    "Search data is updating. Try again when preparation finishes."
                )
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                self._condition.notify_all()

    async def _wake_on_cancel(self, cancelled: asyncio.Event) -> None:
        """Notify the drain condition as soon as the caller's cancel event fires."""
        await cancelled.wait()
        async with self._condition:
            self._condition.notify_all()

    @asynccontextmanager
    async def update(self, cancelled: asyncio.Event | None = None) -> AsyncIterator[None]:
        """Wait for admitted searches, releasing the admission barrier even on cancellation."""
        async with self._condition:
            self._writers += 1
        try:
            async with self._writer_lock:
                async with self._condition:
                    if cancelled is None:
                        await self._condition.wait_for(lambda: self._readers == 0)
                    else:
                        watcher = asyncio.create_task(self._wake_on_cancel(cancelled))
                        try:
                            await self._condition.wait_for(
                                lambda: self._readers == 0 or cancelled.is_set()
                            )
                        finally:
                            watcher.cancel()
                        if cancelled.is_set():
                            raise JobCancelledError("cancelled by operator")
                yield
        finally:
            async with self._condition:
                self._writers -= 1
                self._condition.notify_all()
