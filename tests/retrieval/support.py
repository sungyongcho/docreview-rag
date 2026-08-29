"""Shared retrieval test payloads and SQL helpers."""

from typing import Any

from sqlalchemy.dialects import postgresql

from app.ingestion.chunk import compose_index_text
from app.retrieval.types import ChunkHit

SOURCE_SHA256 = "a" * 64


class NoOpTransaction:
    """Provide the async context-manager surface used by session fakes."""

    async def __aenter__(self) -> None:
        """Enter a transaction-free test context."""

    async def __aexit__(self, *_args: object) -> None:
        """Leave a transaction-free test context."""


class RecordingSession:
    """Record statements and return one scenario-owned fake result."""

    def __init__(self, result: Any, *, transaction_active: bool = False) -> None:
        self.result = result
        self.transaction_active = transaction_active
        self.statements: list[Any] = []

    def begin(self) -> NoOpTransaction:
        """Return the shared no-op transaction context."""
        return NoOpTransaction()

    def in_transaction(self) -> bool:
        """Expose the configured transaction state."""
        return self.transaction_active

    async def execute(self, statement: Any) -> Any:
        """Record one statement and return the configured result."""
        self.statements.append(statement)
        return self.result


def hit_values(**changes: Any) -> dict[str, Any]:
    """Return one valid hit payload with optional replacements."""
    body = "Research and development expenses increased."
    context_header = "NVDA FY2024 · Item 7"
    values: dict[str, Any] = {
        "chunk_id": 10,
        "doc_id": "NVDA-FY2024",
        "item": "7",
        "kind": "text",
        "citation": "NVDA FY2024 · Item 7",
        "start_char": 100,
        "end_char": 160,
        "source_sha256": SOURCE_SHA256,
        "body": body,
        "context_header": context_header,
        "index_text": compose_index_text(context_header, body),
        "score": 0.75,
    }
    values.update(changes)
    return values


def hit(chunk_id: int, score: float, **changes: Any) -> ChunkHit:
    """Build a valid hit with an identity-specific source span."""
    start = changes.pop("start_char", chunk_id * 100)
    return ChunkHit(
        **hit_values(
            chunk_id=chunk_id,
            score=score,
            start_char=start,
            end_char=start + 50,
            **changes,
        )
    )


def normalized_sql(statement: Any) -> tuple[str, dict[str, object]]:
    """Compile PostgreSQL SQL with normalized whitespace."""
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).split()), compiled.params
