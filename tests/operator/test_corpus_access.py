"""Search admission, draining, and cancellation around local corpus updates."""

import asyncio

import pytest

from app.api.errors import ApiProblemError
from app.api.runtime import RuntimeApiServices
from app.operator.corpus_access import CorpusAccess, CorpusUpdatingError
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def test_writer_drains_existing_searches_and_rejects_new_requests():
    """A waiting writer closes admission without interrupting either existing reader."""

    async def exercise():
        access = CorpusAccess()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def write():
            """Record entry only after all existing readers leave."""
            async with access.update():
                entered.set()
                await release.wait()

        async with access.search():
            async with access.search():
                writer = asyncio.create_task(write())
                await asyncio.sleep(0)
                assert access.updating
                assert not entered.is_set()
                with pytest.raises(CorpusUpdatingError):
                    async with access.search():
                        pytest.fail("New search was admitted")
            assert not entered.is_set()
        await asyncio.wait_for(entered.wait(), 1)
        release.set()
        await writer
        assert not access.updating
        async with access.search():
            pass

    asyncio.run(exercise())


def test_cancelled_waiting_writer_reopens_admission():
    """Cancelling a writer waiting for readers cannot leave searches permanently blocked."""

    async def exercise():
        access = CorpusAccess()

        async def write():
            """Wait for the active reader before writing."""
            async with access.update():
                pytest.fail("Writer must still be waiting")

        async with access.search():
            writer = asyncio.create_task(write())
            await asyncio.sleep(0)
            writer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await writer
            assert not access.updating
            async with access.search():
                pass

    asyncio.run(exercise())


def test_failed_writer_reopens_admission_and_runtime_returns_typed_error():
    """HTTP admission exposes an actionable code and writer failure releases the barrier."""

    async def exercise():
        runtime = RuntimeApiServices(embedding_provider=DeterministicEmbeddingProvider())
        with pytest.raises(ValueError, match="failed update"):
            async with runtime.corpus_access.update():
                with pytest.raises(ApiProblemError) as captured:
                    async with runtime.search_access():
                        pytest.fail("Search entered during update")
                assert captured.value.error.code == "corpus_updating"
                assert captured.value.status_code == 503
                raise ValueError("failed update")
        async with runtime.search_access():
            pass

    asyncio.run(exercise())
