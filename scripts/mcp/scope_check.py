"""Check question-scoped fetches over real MCP and the read-only database, without a model.

Usage, from the repository root::

    python -m scripts.mcp.scope_check --issuer AMD --years 2023 2024

Model decisions are scripted and retrieval returns the first stored chunk for each
filter, so the check is free; MCP transport, validation, the fetch guard and
body reads from the configured database are real. It never writes to the database.
"""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

FAILING_QUERY = "fail-second-year"


@dataclass(frozen=True)
class Question:
    """One scripted question and what it must produce."""

    name: str
    steps: tuple[tuple[str, dict[str, Any]], ...]
    status: str
    reads: tuple[int, ...]
    rejected: tuple[int, ...]


def questions(
    issuer: str, first_year: int, second_year: int, first: int, second: int
) -> tuple[Question, ...]:
    """Build the six scope questions for two chunks from two fiscal years."""
    search = {"query": "revenue", "issuers": [issuer], "fiscal_years": [first_year]}
    later = search | {"fiscal_years": [second_year]}
    compare = {"query": "revenue", "issuer": issuer, "fiscal_years": [first_year, second_year]}

    def fetch(chunk_id: object) -> tuple[str, dict[str, Any]]:
        """Ask to read one chunk body."""
        return ("fetch_chunk", {"chunk_id": chunk_id})

    return (
        Question(
            "first question accumulates both years",
            (
                fetch(first),
                ("search_filings", search),
                ("search_filings", later),
                fetch(first),
                fetch(second),
            ),
            "ok",
            (first, second),
            (0,),
        ),
        Question(
            "next question on the same connection starts empty",
            (fetch(first), fetch(second), ("search_filings", later), fetch(second), fetch(first)),
            "ok",
            (second,),
            (0, 1, 4),
        ),
        Question(
            "empty search cannot grant access",
            (("search_filings", search | {"query": "empty"}), fetch(first)),
            "ok",
            (),
            (1,),
        ),
        Question(
            "failed comparison ends the run as a tool error",
            (("compare_years", compare | {"query": FAILING_QUERY}), fetch(first), fetch(second)),
            "tool_error",
            (),
            (0,),
        ),
        Question(
            "successful comparison grants both returned ids",
            (("compare_years", compare), fetch(first), fetch(second)),
            "ok",
            (first, second),
            (),
        ),
        Question(
            "schema validation precedes the fetch guard",
            (fetch([]), fetch(0)),
            "ok",
            (),
            (0, 1),
        ),
    )


def record(log_path: Path, event: dict[str, Any]) -> None:
    """Append one data-layer event outside the stdout protocol stream."""
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


async def serve(log_path: Path, failing_year: int) -> None:
    """Serve the filings tools over read-only rows with deterministic retrieval."""
    from unittest.mock import patch

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.agent.tools.filings import build_default_registry
    from app.db.models import Chunk, Document
    from app.mcp.filings_server import serve as serve_stdio
    from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
    from app.retrieval.types import RetrievalFilters
    from scripts.mcp.live import read_only_engine

    async def retrieve(session: AsyncSession, query: str, **kwargs: object) -> SimpleNamespace:
        """Return the first stored chunk matching the filters, or a controlled outcome."""
        filters = kwargs["filters"]
        assert isinstance(filters, RetrievalFilters)
        if query == "empty":
            return SimpleNamespace(hits=())
        if query == FAILING_QUERY and filters.fiscal_years == (failing_year,):
            raise RuntimeError("controlled retrieval failure")
        statement = select(Chunk).join(Document, Document.doc_id == Chunk.doc_id)
        if filters.issuers:
            statement = statement.where(Document.issuer.in_(filters.issuers))
        if filters.fiscal_years:
            statement = statement.where(Document.fiscal_year.in_(filters.fiscal_years))
        chunk = await session.scalar(statement.order_by(Chunk.id).limit(1))
        if chunk is None:
            return SimpleNamespace(hits=())
        hit = SimpleNamespace(
            chunk_id=chunk.id,
            doc_id=chunk.doc_id,
            citation=chunk.citation,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            source_sha256=chunk.source_sha256,
            score=1.0,
            index_text=chunk.body,
        )
        return SimpleNamespace(hits=(hit,))

    original_get = AsyncSession.get

    async def recorded_get(self: AsyncSession, entity: type[Chunk], ident: int) -> Chunk | None:
        """Record full-body reads while keeping the real database lookup."""
        record(log_path, {"event": "body_load", "chunk_id": ident})
        return await original_get(self, entity, ident)

    engine = read_only_engine()
    try:
        registry = build_default_registry(
            async_sessionmaker(engine, expire_on_commit=False),
            embedding_provider=DeterministicEmbeddingProvider(),
        )
        with (
            patch("app.agent.tools.filings.retrieve", retrieve),
            patch.object(AsyncSession, "get", recorded_get),
        ):
            await serve_stdio(registry)
    finally:
        await engine.dispose()


async def first_chunk(issuer: str, year: int) -> int:
    """Find the first stored chunk of one filing year."""
    from sqlalchemy import select

    from app.db.models import Chunk, Document
    from scripts.mcp.live import read_only_engine

    engine = read_only_engine()
    try:
        async with engine.connect() as connection:
            chunk_id = await connection.scalar(
                select(Chunk.id)
                .join(Document, Document.doc_id == Chunk.doc_id)
                .where(Document.issuer == issuer, Document.fiscal_year == year)
                .order_by(Chunk.id)
                .limit(1)
            )
    finally:
        await engine.dispose()
    if chunk_id is None:
        raise SystemExit(f"no stored chunk for {issuer} {year}")
    return chunk_id


async def check(issuer: str, years: Sequence[int]) -> list[dict[str, Any]]:
    """Run every question through one MCP connection and compare actual reads."""
    from mcp import Client, StdioServerParameters

    from app.agent.loop import run_agent
    from app.agent.provider import DeterministicToolProvider, ProviderTurn
    from app.agent.tools.filings import build_default_registry
    from app.agent.types import ToolCall
    from app.db.session_factory import default_session_factory
    from app.mcp.client import mcp_tool_registry

    first_year, second_year = years
    first, second = await first_chunk(issuer, first_year), await first_chunk(issuer, second_year)

    def turn(name: str, arguments: dict[str, Any]) -> ProviderTurn:
        """Build one scripted model decision."""
        call = ToolCall(call_id="call", name=name, arguments_json=json.dumps(arguments))
        return ProviderTurn(output_text="", input_tokens=0, output_tokens=0, tool_calls=(call,))

    finish = turn(
        "final_answer",
        {
            "label": "NOT_IN_DOCS",
            "answer": "NOT_IN_DOCS",
            "citations": [],
            "rationale": "This check covers dispatch, not answer quality.",
        },
    )
    rows = []
    with TemporaryDirectory(prefix="mcp-scope-") as temporary:
        log_path = Path(temporary) / "events.jsonl"
        log_path.touch()
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "scripts.mcp.scope_check", "serve", str(log_path), str(second_year)],
            env=dict(os.environ),
        )
        async with Client(server, mode="2026-07-28", read_timeout_seconds=30) as client:
            contracts = build_default_registry(default_session_factory)
            bridge = await mcp_tool_registry(client, contracts)
            for question in questions(issuer, first_year, second_year, first, second):
                start = len(log_path.read_text().splitlines())
                result = await run_agent(
                    question.name,
                    locale="en",
                    registry=bridge,
                    provider=DeterministicToolProvider(
                        [*(turn(name, arguments) for name, arguments in question.steps), finish]
                    ),
                )
                events = [json.loads(line) for line in log_path.read_text().splitlines()[start:]]
                reads = tuple(
                    event["chunk_id"] for event in events if event["event"] == "body_load"
                )
                rejected = tuple(
                    index
                    for index, step in enumerate(result.steps)
                    if step.observations and step.observations[0].error is not None
                )
                rows.append(
                    {
                        "question": question.name,
                        "passed": (result.status, reads, rejected)
                        == (question.status, question.reads, question.rejected),
                        "status": result.status,
                        "reads": reads,
                        "rejected": rejected,
                    }
                )
    return rows


def main(argv: Sequence[str] | None = None) -> None:
    """Run the check, or the server subprocess it starts."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["serve"]:
        asyncio.run(serve(Path(argv[1]), int(argv[2])))
        return
    parser = argparse.ArgumentParser(prog="python -m scripts.mcp.scope_check", description=__doc__)
    parser.add_argument("--issuer", default="AMD")
    parser.add_argument("--years", type=int, nargs=2, default=[2023, 2024])
    args = parser.parse_args(argv)
    rows = asyncio.run(check(args.issuer, args.years))
    print(json.dumps(rows, indent=2))
    if not all(row["passed"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
