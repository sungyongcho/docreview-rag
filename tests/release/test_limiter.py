"""Bounded single-process limiter tests."""

import asyncio

from app.release.limiter import InProcessRateLimiter


class Clock:
    """Mutable monotonic clock for deterministic rolling-window tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_minute_limit_reports_retry_and_recovers() -> None:
    """Deny past the minute allowance with a retry delay, and allow again once it passes."""
    clock = Clock()
    limiter = InProcessRateLimiter(
        per_minute=2,
        per_day=5,
        max_clients=3,
        clock=clock,
    )

    first = asyncio.run(limiter.check("client"))
    second = asyncio.run(limiter.check("client"))
    denied = asyncio.run(limiter.check("client"))
    clock.now = 60.1
    recovered = asyncio.run(limiter.check("client"))

    assert first.allowed and first.remaining_minute == 1
    assert second.allowed and second.remaining_minute == 0
    assert not denied.allowed and denied.retry_after_seconds == 60
    assert recovered.allowed


def test_daily_limit_is_rolling_and_not_a_calendar_reset() -> None:
    """Roll the daily window forward from each request rather than resetting at midnight."""
    clock = Clock()
    limiter = InProcessRateLimiter(
        per_minute=1,
        per_day=2,
        max_clients=3,
        clock=clock,
    )

    assert asyncio.run(limiter.check("client")).allowed
    clock.now = 61.0
    assert asyncio.run(limiter.check("client")).allowed
    clock.now = 122.0
    denied = asyncio.run(limiter.check("client"))
    clock.now = 86_400.1
    recovered = asyncio.run(limiter.check("client"))

    assert not denied.allowed
    assert denied.remaining_day == 0
    assert recovered.allowed


def test_client_state_is_bounded_by_lru_eviction() -> None:
    """Bound the tracked clients, evicting the least recently seen."""
    limiter = InProcessRateLimiter(per_minute=1, per_day=1, max_clients=2)

    asyncio.run(limiter.check("one"))
    asyncio.run(limiter.check("two"))
    asyncio.run(limiter.check("three"))

    assert limiter.client_count == 2


def test_concurrent_requests_consume_slots_atomically() -> None:
    """Hand out exactly the allowance when requests arrive together."""
    limiter = InProcessRateLimiter(per_minute=5, per_day=10, max_clients=2)

    async def run() -> list[bool]:
        """Fire the concurrent checks and report which were allowed."""
        decisions = await asyncio.gather(*(limiter.check("same") for _ in range(20)))
        return [decision.allowed for decision in decisions]

    allowed = asyncio.run(run())

    assert sum(allowed) == 5
