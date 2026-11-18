"""Stand-ins for the database objects the tools and scripts open: sessions and engines.

- :class:`FakeSession` serves staged chunk rows by id and records its own lifecycle;
- :class:`FakeSessionFactory` is the ``SessionFactory`` that hands those sessions out;
- :func:`no_session` is the ``SessionFactory`` of a registry whose tools must never run;
- :class:`FakeEngine` stands in for an engine whose only observable use is ``dispose``.
"""

from collections.abc import Callable, Mapping
from typing import Self, cast

from sqlalchemy.ext.asyncio import AsyncSession


def row_id(row: object) -> int:
    """The chunk id a staged row is served under: its ``id`` attribute."""
    chunk_id = getattr(row, "id", None)
    assert isinstance(chunk_id, int), "a staged chunk row needs an integer id"
    return chunk_id


class FakeSession:
    """Duck-typed async session serving staged chunk rows and recording its lifecycle.

    ``get`` serves the row staged under the requested id, nothing for an unknown id,
    or raises the failure staged for that id; ``scalars`` answers the current-evidence
    check with every staged id. ``on_get`` is called with each requested id before it
    is answered, so a server process can log reads where its test can see them.
    Reads open a transaction the way SQLAlchemy autobegins one, and leaving the
    context rolls it back, so a test can tell whether a tool released its session.
    """

    def __init__(
        self,
        *rows: object,
        failures: Mapping[int, BaseException] | None = None,
        on_get: Callable[[int], None] | None = None,
    ) -> None:
        self.rows = {row_id(row): row for row in rows}
        self.failures = dict(failures or {})
        self.on_get = on_get
        self.requested_ids: list[int] = []
        self.transaction_open = False
        self.rollback_count = 0
        self.closed = False

    async def __aenter__(self) -> Self:
        """Enter the session context the way an AsyncSession does."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Roll back any open read transaction and close, mirroring AsyncSession."""
        if self.transaction_open:
            await self.rollback()
        self.closed = True

    async def get(self, model: object, chunk_id: int) -> object | None:
        """Record the requested id, then fail or return the row staged under it."""
        del model
        self.requested_ids.append(chunk_id)
        if self.on_get is not None:
            self.on_get(chunk_id)
        self.transaction_open = True
        failure = self.failures.get(chunk_id)
        if failure is not None:
            raise failure
        return self.rows.get(chunk_id)

    async def scalars(self, statement: object) -> list[int]:
        """Answer the current-evidence check: every staged row is current evidence."""
        del statement
        self.transaction_open = True
        return list(self.rows)

    def in_transaction(self) -> bool:
        """Report whether this fake session currently holds a transaction."""
        return self.transaction_open

    async def rollback(self) -> None:
        """Close the transaction and count the rollback."""
        self.transaction_open = False
        self.rollback_count += 1


class FakeSessionFactory:
    """Session factory handing out one :class:`FakeSession` per call and keeping each.

    Every session serves the same staged ``rows`` and ``failures`` and reports reads
    to the same ``on_get``.
    """

    def __init__(
        self,
        *rows: object,
        failures: Mapping[int, BaseException] | None = None,
        on_get: Callable[[int], None] | None = None,
    ) -> None:
        self.rows = rows
        self.failures = failures
        self.on_get = on_get
        self.sessions: list[FakeSession] = []

    def __call__(self) -> AsyncSession:
        """Produce one fresh fake session per call, the way a sessionmaker does."""
        session = FakeSession(*self.rows, failures=self.failures, on_get=self.on_get)
        self.sessions.append(session)
        # The app's SessionFactory names AsyncSession; the fake offers the four methods
        # the tools call, so it stands in for one here and nowhere else.
        return cast(AsyncSession, session)


def no_session() -> AsyncSession:
    """Session factory for a registry used only for its tool contracts.

    Such a registry supplies parameter models, descriptions and evidence extraction;
    its run functions execute elsewhere (over MCP), so opening a session is a bug.
    """
    raise AssertionError("these tool contracts must never open a database session")


class FakeEngine:
    """Engine stand-in for code that never queries it; it records the pool release."""

    def __init__(self) -> None:
        self.dispose_count = 0

    @property
    def disposed(self) -> bool:
        """Whether the pool has been released at least once."""
        return self.dispose_count > 0

    async def dispose(self) -> None:
        """Count one release of the connection pool."""
        self.dispose_count += 1
