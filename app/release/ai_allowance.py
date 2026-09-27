"""Durable single-host OpenAI allowance shared by processes on one mounted volume."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
import logging
import math
from pathlib import Path
import secrets
import sqlite3
import time

MICRO = Decimal(1_000_000)
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """One allow or deny decision with bounded retry metadata."""

    allowed: bool
    retry_after_seconds: int
    remaining_minute: int
    remaining_day: int
    minute_reset_seconds: int
    day_reset_seconds: int


class AIAllowanceError(ValueError):
    """Carry a limit or ledger failure through provider and runtime exception boundaries."""

    def __init__(self, code: str, message: str, retry_after: int, reset: datetime | None = None):
        """Retain retry metadata without client identities or storage paths."""
        super().__init__(message)
        self.code = code
        self.retry_after = max(1, retry_after)
        self.reset = reset

    @property
    def status_code(self) -> int:
        """Distinguish unavailable enforcement from a successfully enforced limit."""
        return 503 if self.code == "allowance_unavailable" else 429


class SharedAIAllowance:
    """Atomically retain per-client request windows and the UTC-day cost cap across restarts.

    The middleware admits each execution request before reading its body. Actual provider
    calls independently reserve conservative costs, including multiple calls per request.
    """

    def __init__(self, path: Path, daily_limit: Decimal, per_minute: int, per_day: int):
        """Open the configured persistent volume, failing closed on storage errors."""
        self.path = path
        self.daily_limit = daily_limit
        self.per_minute = per_minute
        self.per_day = per_day
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS calls (stamp REAL NOT NULL, kind TEXT NOT NULL, "
                "client TEXT, amount INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS calls_window ON calls(kind, client, stamp)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS identity "
                "(id INTEGER PRIMARY KEY CHECK(id=1), salt BLOB NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO identity VALUES (1, ?)", (secrets.token_bytes(32),)
            )
            self.salt = bytes(
                connection.execute("SELECT salt FROM identity WHERE id=1").fetchone()[0]
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Use a bounded SQLite lock wait; writers serialize before reading capacity."""
        try:
            connection = sqlite3.connect(self.path, timeout=10)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
        except sqlite3.Error as error:
            logger.exception("Public allowance ledger unavailable")
            raise AIAllowanceError(
                "allowance_unavailable", "The service request allowance is unavailable.", 1
            ) from error

    def _rate_decision(
        self, connection: sqlite3.Connection, client: str, now: float
    ) -> RateLimitDecision:
        """Inspect a rolling IP window inside the caller's locked transaction."""
        connection.execute("DELETE FROM calls WHERE stamp <= ?", (now - 172800,))
        stamps = [
            row[0]
            for row in connection.execute(
                "SELECT stamp FROM calls WHERE kind='request' AND client=? "
                "AND stamp>? ORDER BY stamp",
                (client, now - 86400),
            )
        ]
        minute = [stamp for stamp in stamps if stamp > now - 60]
        minute_reset = max(1, math.ceil(minute[0] + 60 - now)) if minute else 0
        day_reset = max(1, math.ceil(stamps[0] + 86400 - now)) if stamps else 0
        allowed = len(minute) < self.per_minute and len(stamps) < self.per_day
        retry = max(
            minute_reset if len(minute) >= self.per_minute else 0,
            day_reset if len(stamps) >= self.per_day else 0,
        )
        return RateLimitDecision(
            allowed,
            retry,
            max(0, self.per_minute - len(minute)),
            max(0, self.per_day - len(stamps)),
            minute_reset,
            day_reset,
        )

    def _rate(self, client: str, *, consume: bool) -> RateLimitDecision:
        """Read or consume rolling IP capacity in one durable transaction."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            decision = self._rate_decision(connection, client, now)
            if consume and decision.allowed:
                connection.execute("INSERT INTO calls VALUES (?, 'request', ?, 0)", (now, client))
                remaining = self._rate_decision(connection, client, now)
                # This request was admitted even if it consumed the final slot.
                return RateLimitDecision(
                    True,
                    remaining.retry_after_seconds,
                    remaining.remaining_minute,
                    remaining.remaining_day,
                    remaining.minute_reset_seconds,
                    remaining.day_reset_seconds,
                )
            return decision

    async def admit(self, client: str) -> RateLimitDecision:
        """Atomically consume one request slot, leaving denied windows unchanged."""
        return await asyncio.to_thread(self._rate, client, consume=True)

    async def peek(self, client: str) -> RateLimitDecision:
        """Inspect an IP window without consuming it."""
        return await asyncio.to_thread(self._rate, client, consume=False)

    def _cost(self, amount: Decimal = Decimal(0)) -> tuple[bool, Decimal, datetime]:
        """Reserve conservative spend without refunds, including ambiguous failures."""
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid API reservation")
        units = int((amount * MICRO).to_integral_value(rounding=ROUND_CEILING))
        ceiling = int(self.daily_limit * MICRO)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = datetime.fromtimestamp(time.time(), UTC)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            spent = connection.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM calls WHERE kind='openai' AND stamp>=?",
                (start.timestamp(),),
            ).fetchone()[0]
            allowed = spent + units <= ceiling
            if allowed:
                if units:
                    connection.execute(
                        "INSERT INTO calls VALUES (?, 'openai', NULL, ?)",
                        (now.timestamp(), units),
                    )
                    spent += units
            return (
                allowed,
                max(Decimal(0), Decimal(ceiling - spent) / MICRO),
                start + timedelta(days=1),
            )

    async def reserve_amount(self, amount: Decimal) -> tuple[bool, Decimal, datetime]:
        """Serialize a provider reservation across all local worker processes."""
        return await asyncio.to_thread(self._cost, amount)

    async def status(self) -> tuple[Decimal, datetime]:
        """Return conservative remaining allowance and the UTC midnight reset."""
        _, remaining, reset = await asyncio.to_thread(self._cost)
        return remaining, reset


active_allowance: ContextVar[SharedAIAllowance | None] = ContextVar(
    "public_ai_allowance", default=None
)


async def reserve_openai(amount: Decimal) -> None:
    """Block an actual OpenAI call before dispatch when shared capacity is exhausted."""
    allowance = active_allowance.get()
    if allowance is None:
        return
    allowed, _, reset = await allowance.reserve_amount(amount)
    if not allowed:
        raise AIAllowanceError(
            "daily_cost_limit",
            f"Shared OpenAI allowance exhausted. Resets at {reset.isoformat()}",
            math.ceil((reset - datetime.now(UTC)).total_seconds()),
            reset,
        )
