"""Serve the real filings MCP server with controlled retrieval and chunk reads.

Run as ``python -m tests.mcp.controlled_filings <log path> [--http PORT]``. Only the
retrieval boundary and the database session are replaced; the registry, validation,
error taxonomy, serialization, argument parsing and the stdio or HTTP transport are
the production code. Every retrieval and body read is appended to the log so a test
can tell which requests reached the data layer; the query ``slow`` blocks until
cancelled and logs how it ended, and ``server_stopped`` marks the transport's exit.
"""

import asyncio
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.filings import build_default_registry
from app.mcp.filings_server import parse_arguments, serve, serve_http
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.types import ChunkHit, RetrievalFilters

SEARCH_CHUNK_ID = 7
FAILING_CHUNK_ID = 13
PRIVATE_DETAIL = "TEST_PRIVATE_DATABASE_DETAIL"
SLOW_SECONDS = 30


def fixture_hit(chunk_id: int) -> ChunkHit:
    """Make a clearly synthetic candidate whose identity follows its chunk id."""
    body = f"Synthetic TestCo evidence {chunk_id}: revenue was 100 USD."
    return ChunkHit(
        chunk_id=chunk_id,
        doc_id=f"TEST-{chunk_id}",
        item="7",
        kind="text",
        citation=f"Synthetic TestCo {chunk_id}",
        start_char=0,
        end_char=len(body),
        source_sha256=hashlib.sha256(body.encode()).hexdigest(),
        body=body,
        context_header="",
        index_text=body,
        score=0.5,
    )


class ControlledSession:
    """Async session double that serves fixture chunks and logs each body read."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path

    async def __aenter__(self) -> ControlledSession:
        """Enter the context the way an AsyncSession does."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Nothing to roll back; reads have no transaction here."""

    async def get(self, model: object, chunk_id: int) -> SimpleNamespace | None:
        """Return a fixture chunk, nothing for unknown ids, or a database failure."""
        del model
        record(self.log_path, {"event": "body_load", "chunk_id": chunk_id})
        if chunk_id == FAILING_CHUNK_ID:
            raise RuntimeError(PRIVATE_DETAIL)
        if chunk_id not in (SEARCH_CHUNK_ID, 2023, 2024):
            return None
        hit = fixture_hit(chunk_id)
        return SimpleNamespace(
            id=hit.chunk_id,
            doc_id=hit.doc_id,
            citation=hit.citation,
            start_char=hit.start_char,
            end_char=hit.end_char,
            source_sha256=hit.source_sha256,
            context_header=hit.context_header,
            body=hit.body,
            kind=hit.kind,
        )

    async def scalars(self, statement: object) -> list[int]:
        """Answer the current-evidence check: every fixture chunk is current evidence."""
        del statement
        return [SEARCH_CHUNK_ID, 2023, 2024]


def record(log_path: Path, event: dict[str, object]) -> None:
    """Append one data-layer event outside the stdout protocol stream."""
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


def controlled_retrieve(log_path: Path):
    """Build a retrieval double whose outcome is chosen by the query text."""

    async def retrieve(session: object, query: str, **kwargs: object) -> SimpleNamespace:
        """Log the request, then return fixed hits, no hits, or a failure."""
        filters = kwargs["filters"]
        assert isinstance(filters, RetrievalFilters)
        years = filters.fiscal_years
        record(
            log_path,
            {
                "event": "retrieval",
                "query": query,
                "k": kwargs["k"],
                "filters": filters.model_dump(mode="json"),
            },
        )
        if query == "slow":
            record(log_path, {"event": "slow_started"})
            try:
                await asyncio.sleep(SLOW_SECONDS)
                record(log_path, {"event": "slow_completed"})
            except asyncio.CancelledError:
                record(log_path, {"event": "slow_cancelled"})
                raise
            finally:
                record(log_path, {"event": "slow_finally"})
        if query == "fail" or (query == "fail-2024" and years == (2024,)):
            raise RuntimeError(PRIVATE_DETAIL)
        if query == "both-empty" or query == "no-match":
            return SimpleNamespace(hits=(), holds=())
        if query == "empty-2024" and years == (2024,):
            return SimpleNamespace(hits=(), holds=())
        chunk_id = years[0] if len(years) == 1 else SEARCH_CHUNK_ID
        return SimpleNamespace(hits=(fixture_hit(chunk_id),), holds=())

    return retrieve


async def main(
    log_path: Path, http_port: int | None = None, *, include_cells: bool = False
) -> None:
    """Serve the production registry with only the data layer replaced.

    ``http_port`` selects Streamable HTTP as in the product entry point; the
    ``finally`` block stands in for its database cleanup.
    """
    registry = build_default_registry(
        lambda: cast(AsyncSession, ControlledSession(log_path)),
        embedding_provider=DeterministicEmbeddingProvider(),
        include_cells=include_cells,
    )
    try:
        with patch("app.agent.tools.filings.retrieve", controlled_retrieve(log_path)):
            if http_port is None:
                await serve(registry)
            else:
                await serve_http(registry, port=http_port)
    finally:
        record(log_path, {"event": "server_stopped"})


if __name__ == "__main__":
    arguments = parse_arguments(sys.argv[2:])
    asyncio.run(main(Path(sys.argv[1]), arguments.http, include_cells=arguments.include_cells))
