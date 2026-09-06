import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
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


@dataclass(slots=True)
class _ClientWindow:
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

            if minute_count >= self._per_minute:
                minute_start = next(
                    timestamp for timestamp in window.timestamps if timestamp > minute_cutoff
                )
                retry = max(1, math.ceil(minute_start + MINUTE_SECONDS - now))
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry,
                    remaining_minute=0,
                    remaining_day=max(0, self._per_day - day_count),
                )
            if day_count >= self._per_day:
                retry = max(1, math.ceil(window.timestamps[0] + DAY_SECONDS - now))
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry,
                    remaining_minute=max(0, self._per_minute - minute_count),
                    remaining_day=0,
                )

            window.timestamps.append(float(now))
            return RateLimitDecision(
                allowed=True,
                retry_after_seconds=0,
                remaining_minute=self._per_minute - minute_count - 1,
                remaining_day=self._per_day - day_count - 1,
            )
