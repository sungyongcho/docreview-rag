"""The one type every component uses for "something that opens a database session"."""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

# Services receive a factory instead of a session so each unit of work owns its own
# session and transaction. This module only names the shape; it creates no engine, so
# importing it never loads settings or connects to anything.
type SessionFactory = Callable[[], AsyncSession]
