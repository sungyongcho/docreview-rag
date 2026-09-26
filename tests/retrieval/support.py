"""Shared retrieval test payloads and SQL helpers."""

import hashlib
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.ingestion.chunking import compose_index_text
from app.ingestion.parsing.models import Block, ParsedFiling, Section
from app.retrieval.types import ChunkHit
from tests.ingestion.support import filing_document, filing_source

SOURCE_SHA256 = "a" * 64


def fake_sentence_transformers(
    monkeypatch: pytest.MonkeyPatch,
    **attributes: object,
) -> None:
    """Expose fake encoders through the optional third-party module name."""
    module = ModuleType("sentence_transformers")
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


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


def retrieval_filing(tmp_path: Path, *, other: bool = False) -> ParsedFiling:
    """Build parsed source blocks tied to exact real fixture bytes and metadata."""
    bodies = (
        ["Other issuer source evidence."]
        if other
        else [
            "Research expense research expense increased in fiscal 2024.",
            "Inventory and supply obligations decreased during the year.",
            "Research expense appeared in one collaboration agreement.",
        ]
    )
    document = filing_document(
        issuer="AMD" if other else "NVDA",
        filing_id="0001045810-24-000002" if other else "0001045810-24-000001",
    )
    path = tmp_path / f"{document.document_id}.html"
    raw = "\n".join(bodies)
    path.write_text(raw)
    source = filing_source(path, document=document)
    sections = []
    offset = 0
    for index, body in enumerate(bodies):
        sections.append(
            Section(
                "II",
                "7" if index < 2 else "8",
                "",
                "",
                [
                    Block(
                        "paragraph",
                        body,
                        source_pos=offset,
                        end_pos=offset + len(body),
                        source_group=index,
                    )
                ],
            )
        )
        offset += len(body) + 1
    return ParsedFiling(
        source=source,
        source_length=len(raw),
        source_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        sections=sections,
    )
