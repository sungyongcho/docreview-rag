"""Measured stage ordering, failures, cancellation, and request isolation."""

import asyncio

import pytest

from app.observability.stages import record_stages, stage, stage_metadata


def test_stage_starts_before_work_and_ends_on_handled_and_raised_failures() -> None:
    """Report real start and end observations without estimating an active duration."""
    events = []

    async def observe(event) -> None:
        """Capture transitions without invoking providers or persistence."""
        events.append(event)

    async def exercise() -> None:
        """Use real asynchronous boundaries for completed and failed stages."""
        with record_stages(observe):
            async with stage("grade") as measurement:
                assert events[-1].phase == "start" and events[-1].elapsed_ms is None
                measurement.failed = True
            with pytest.raises(RuntimeError):
                async with stage("check"):
                    raise RuntimeError("failure")
            metadata = stage_metadata()
            assert [event["node"] for event in metadata["stages"]] == ["grade", "check"]
        assert stage_metadata() == {}

    asyncio.run(exercise())
    assert [event.phase for event in events] == ["start", "end", "start", "end"]
    assert [event.status for event in events if event.phase == "end"] == ["failed", "failed"]
    assert all(event.elapsed_ms >= 0 for event in events if event.phase == "end")


def test_independent_reviews_never_share_stage_metadata() -> None:
    """Concurrent requests get separate clocks and completed histories."""

    async def review(node):
        """Yield once so both recorders are active concurrently."""
        with record_stages():
            async with stage(node):
                await asyncio.sleep(0)
            return stage_metadata()

    async def exercise():
        """Run independent review entry points in distinct tasks."""
        return await asyncio.gather(review("grade"), review("chat"))

    first, second = asyncio.run(exercise())
    assert [event["node"] for event in first["stages"]] == ["grade"]
    assert [event["node"] for event in second["stages"]] == ["chat"]


def test_routing_metadata_appears_only_after_actual_resolution() -> None:
    """Keep the selected mode distinct from the completed server scope."""
    events = []
    resolved = {"source": "alias", "filters": {"registries": ["dart"], "issuers": ["005930"]}}

    async def observe(event) -> None:
        """Collect start and end scope payloads without model calls."""
        events.append(event)

    async def exercise() -> None:
        """Publish actual metadata only after the resolution boundary completes."""
        with record_stages(observe):
            async with stage("route") as measurement:
                assert events[-1].resolved_scope is None
                measurement.resolved_scope = resolved
            async with stage("grade"):
                pass

    asyncio.run(exercise())
    assert events[1].resolved_scope == resolved
    assert all(event.resolved_scope is None for event in (events[0], events[2], events[3]))
