"""In-process rate limiting with rolling minute and day windows."""

import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time as datetime_time, timedelta
from decimal import Decimal
import math
import time

MINUTE_SECONDS = 60.0
DAY_SECONDS = 86_400.0


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """One allow or deny decision with bounded retry metadata."""

    allowed: bool
    retry_after_seconds: int
    remaining_minute: int
    remaining_day: int
    minute_reset_seconds: int
    day_reset_seconds: int


@dataclass(slots=True)
class _ClientWindow:
    """One client's request timestamps and when it was last seen."""

    timestamps: deque[float] = field(default_factory=deque)
    last_seen: float = 0.0


class InProcessRateLimiter:
    """Enforce rolling minute/day limits with bounded LRU client state.

    This limiter intentionally targets one process. Multiple workers or replicas each own
    independent counters and require an external shared limiter before public scale-out.
    """

    def __init__(
        self,
        *,
        per_minute: int,
        per_day: int,
        max_clients: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(per_minute, per_day, max_clients) <= 0:
            raise ValueError("rate limits and max_clients must be positive")
        if per_day < per_minute:
            raise ValueError("per_day must be at least per_minute")
        self._per_minute = per_minute
        self._per_day = per_day
        self._max_clients = max_clients
        self._clock = clock
        self._clients: OrderedDict[str, _ClientWindow] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        """Return the current bounded state size for diagnostics and tests."""
        return len(self._clients)

    async def check(self, client_key: str) -> RateLimitDecision:
        """Atomically consume one request slot or return a retry decision."""
        if not isinstance(client_key, str) or not client_key:
            raise ValueError("client_key must be a nonblank string")
        now = self._clock()
        if not isinstance(now, int | float) or not math.isfinite(now) or now < 0:
            raise ValueError("clock must return a finite nonnegative value")

        async with self._lock:
            window = self._clients.pop(client_key, None)
            if window is None:
                if len(self._clients) >= self._max_clients:
                    self._clients.popitem(last=False)
                window = _ClientWindow()
            self._clients[client_key] = window
            window.last_seen = float(now)

            day_cutoff = now - DAY_SECONDS
            while window.timestamps and window.timestamps[0] <= day_cutoff:
                window.timestamps.popleft()

            minute_cutoff = now - MINUTE_SECONDS
            minute_count = sum(timestamp > minute_cutoff for timestamp in window.timestamps)
            day_count = len(window.timestamps)
            minute_start = next(
                (timestamp for timestamp in window.timestamps if timestamp > minute_cutoff), None
            )
            minute_reset = (
                max(1, math.ceil(minute_start + MINUTE_SECONDS - now))
                if minute_start is not None
                else 0
            )
            day_reset = (
                max(1, math.ceil(window.timestamps[0] + DAY_SECONDS - now))
                if window.timestamps
                else 0
            )

            if minute_count >= self._per_minute:
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=minute_reset,
                    remaining_minute=0,
                    remaining_day=max(0, self._per_day - day_count),
                    minute_reset_seconds=minute_reset,
                    day_reset_seconds=day_reset,
                )
            if day_count >= self._per_day:
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=day_reset,
                    remaining_minute=max(0, self._per_minute - minute_count),
                    remaining_day=0,
                    minute_reset_seconds=minute_reset,
                    day_reset_seconds=day_reset,
                )

            window.timestamps.append(float(now))
            minute_reset = max(1, math.ceil(window.timestamps[-1] + MINUTE_SECONDS - now))
            day_reset = max(1, math.ceil(window.timestamps[0] + DAY_SECONDS - now))
            return RateLimitDecision(
                allowed=True,
                retry_after_seconds=0,
                remaining_minute=self._per_minute - minute_count - 1,
                remaining_day=self._per_day - day_count - 1,
                minute_reset_seconds=minute_reset,
                day_reset_seconds=day_reset,
            )

    async def peek(self, client_key: str) -> RateLimitDecision:
        """Inspect one client's remaining allowance without consuming a slot."""
        now = self._clock()
        if not isinstance(now, int | float) or not math.isfinite(now) or now < 0:
            raise ValueError("clock must return a finite nonnegative value")
        async with self._lock:
            window = self._clients.get(client_key)
            timestamps = () if window is None else tuple(window.timestamps)
            minute_values = tuple(value for value in timestamps if value > now - MINUTE_SECONDS)
            day_values = tuple(value for value in timestamps if value > now - DAY_SECONDS)
            minute = len(minute_values)
            day = len(day_values)
        minute_reset = (
            max(1, math.ceil(minute_values[0] + MINUTE_SECONDS - now)) if minute_values else 0
        )
        day_reset = max(1, math.ceil(day_values[0] + DAY_SECONDS - now)) if day_values else 0
        retry = (
            minute_reset if minute >= self._per_minute else day_reset if day >= self._per_day else 0
        )
        return RateLimitDecision(
            allowed=minute < self._per_minute and day < self._per_day,
            retry_after_seconds=retry,
            remaining_minute=max(0, self._per_minute - minute),
            remaining_day=max(0, self._per_day - day),
            minute_reset_seconds=minute_reset,
            day_reset_seconds=day_reset,
        )


class DailyCostLimiter:
    """Reserve worst-case provider spend against one UTC-day process budget."""

    def __init__(
        self,
        *,
        daily_limit_usd: Decimal,
        reservation_usd: Decimal,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        if daily_limit_usd <= 0 or reservation_usd <= 0:
            raise ValueError("cost limits must be positive")
        if reservation_usd > daily_limit_usd:
            raise ValueError("one reservation must not exceed the daily limit")
        self._daily_limit = daily_limit_usd
        self._reservation = reservation_usd
        self._today = today
        self._day = today()
        self._reserved = Decimal("0")
        self._lock = asyncio.Lock()

    async def reserve(self) -> tuple[bool, Decimal]:
        """Reserve one maximum request cost and return remaining budget."""
        async with self._lock:
            current_day = self._today()
            if current_day != self._day:
                self._day = current_day
                self._reserved = Decimal("0")
            if self._reserved + self._reservation > self._daily_limit:
                return False, self._daily_limit - self._reserved
            self._reserved += self._reservation
            return True, self._daily_limit - self._reserved

    async def remaining(self) -> Decimal:
        """Return today's unreserved allowance without reserving provider spend."""
        remaining, _reset = await self.status()
        return remaining

    async def status(self) -> tuple[Decimal, datetime]:
        """Return unreserved allowance and the next UTC calendar reset."""
        async with self._lock:
            current_day = self._today()
            if current_day != self._day:
                self._day = current_day
                self._reserved = Decimal("0")
            reset = datetime.combine(current_day + timedelta(days=1), datetime_time.min, tzinfo=UTC)
            return self._daily_limit - self._reserved, reset
