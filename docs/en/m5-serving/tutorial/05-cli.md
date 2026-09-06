# M5.2 Tutorial 5 — The CLI is a first-class citizen

It has to be usable straight from a terminal without Docker and without a server. Spinning up a container to try one query during development is waste.

And the CLI must **fail predictably.** Empty query, invalid limit, missing file, broken JSON, unreachable dependency — each must produce a stable exit code and JSON, because scripts will call this CLI.

**Prerequisite:** `api/runtime.py` and `main.py` from tutorial 4 are written.

### Exit codes split by meaning

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | invalid input (empty query, negative k) |
| 3 | invalid file (missing, broken JSON) |
| 4 | dependency unreachable (database, provider) |

Splitting 2 from 3 is the point. Both are "the user's fault," but **the fix differs.** For 2 you fix the command; for 3 you fix the file. A script can decide whether retrying helps.

4 is separate for the same reason. An infrastructure problem may succeed if **the same command runs again later.**

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `ExitCode` and `CliError` | **Write the record declarations** | Splitting exit codes by meaning |
| `CliArgumentParser` | **Review the design decision** | Why argparse's default exit code gets overridden |
| `_validate_arguments` | **Implement** the validation yourself | The boundary that rejects before I/O |
| `_retrieve` and `_ingest` | **Write the field mapping** | Emitting the same evidence shape as HTTP |
| `main` | **Implement** the exception conversion yourself | Where an exception becomes an exit code |

### 1. Splitting exit codes by meaning

#### Create `app/cli.py` — module header

**Learning action — define the structure:** `app.api.runtime` is among the imports. The CLI uses **the same seam** as HTTP.

```python
"""Deterministic command-line entrypoints for retrieval, ingestion, and serving."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from enum import IntEnum
import json
from pathlib import Path
import sys
from typing import Any, Literal, TextIO

from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.retrieval.types import ChunkHit, RetrievalFilters

ProviderName = Literal["deterministic", "openai"]

```

#### Extend `app/cli.py` — exit codes and the parser base

**Learning action — write the record declarations:** note what `CliArgumentParser` overrides.

<!-- src: app/cli.py::ExitCode,CliArgumentParser -->
```python
class ExitCode(IntEnum):
    """Stable process exit codes for expected CLI outcomes."""

    OK = 0
    INVALID_INPUT = 2
    INVALID_FILE = 3
    UNAVAILABLE = 4


class CliError(Exception):
    """An expected CLI failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, exit_code: ExitCode) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class CliArgumentParser(argparse.ArgumentParser):
    """Convert argparse failures into the same JSON envelope as runtime failures."""

    def error(self, message: str) -> None:
        """Raise a structured CliError instead of printing usage and exiting."""
        raise CliError("invalid_arguments", message, ExitCode.INVALID_INPUT)
```

**What to look for in the code**

- `ExitCode` is an `IntEnum`, so `sys.exit(ExitCode.INVALID_INPUT)` becomes a plain 2.
- `CliArgumentParser.error` aligns argparse's default exit code 2 with our `INVALID_INPUT`. They coincide, and aligning them **explicitly** keeps the contract if argparse changes.
- `CliError` carries code, message, and exit code together. Whoever raises decides the exit code too.

### 2. Rejecting before I/O

#### Extend `app/cli.py` — argument definitions

**Learning action — define the structure:** note what each of the three subcommands accepts.

<!-- src: app/cli.py::_add_retrieve_arguments,arguments -->
```python
def _add_retrieve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True, help="Nonblank retrieval query.")
    parser.add_argument("-k", type=int, default=5, help="Number of fused hits to return.")
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Candidates per retrieval component; defaults to max(20, 4 * k).",
    )
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai"),
        default="deterministic",
        help="Embedding provider; deterministic is the offline default.",
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    parser.add_argument("--doc-id", action="append", default=[], help="Exact document filter.")
    parser.add_argument("--ticker", action="append", default=[], help="Exact ticker filter.")
    parser.add_argument(
        "--fiscal-year",
        action="append",
        default=[],
        type=int,
        help="Exact fiscal-year filter.",
    )
    parser.add_argument("--form", action="append", default=[], help="Exact filing-form filter.")
    parser.add_argument("--item", action="append", default=[], help="Exact filing-item filter.")
    parser.add_argument(
        "--kind",
        action="append",
        default=[],
        choices=("text", "table"),
        help="Exact chunk-kind filter.",
    )


def _add_ingest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the corpus manifest JSON file.",
    )
    parser.add_argument(
        "--expected-documents",
        type=int,
        default=20,
        help="Fail unless the manifest contains this many documents.",
    )
    parser.add_argument(
        "--chunk-batch-size",
        type=int,
        default=500,
        help="Number of chunk rows per PostgreSQL upsert statement.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create missing tables before ingestion; existing tables are not migrated.",
    )


def _add_serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="Interface address to bind.")
    parser.add_argument("--port", type=int, default=8000, help="TCP port to bind.")
    parser.add_argument("--workers", type=int, default=1, help="Number of Uvicorn workers.")
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        default="info",
        help="Uvicorn log level.",
    )


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse one explicit runtime command without opening files or services."""
    parser = CliArgumentParser(prog="docreview", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    retrieve = subparsers.add_parser("retrieve", help="Retrieve cited filing evidence.")
    ingest = subparsers.add_parser("ingest", help="Upsert one local corpus manifest.")
    serve = subparsers.add_parser("serve", help="Run the FastAPI application with Uvicorn.")
    _add_retrieve_arguments(retrieve)
    _add_ingest_arguments(ingest)
    _add_serve_arguments(serve)
    return parser.parse_args(argv)
```

**What to look for in the code**

- `arguments()` opens no file and no service. Separating parsing from execution makes argument validation testable on its own and catches a malformed command before it reaches the database.
- `required=True` forces a subcommand. Without it, typing `docreview` alone exits with status 0 having done nothing, and a calling script reads that as success.
- The argument definitions are extracted into their own functions. As commands accumulate, `arguments()` grows by two lines per command — the `add_parser` call and the `_add_*_arguments` call — and the entrypoint stays readable.

#### Extend `app/cli.py` — validation and projection

**Learning action — implement the validation:** implement `_validate_arguments` yourself. Note that it performs no I/O at all.

<!-- src: app/cli.py::_validate_arguments,_evidence_payload -->
```python
def _validate_arguments(args: argparse.Namespace) -> None:
    if args.command == "retrieve":
        if not args.query.strip():
            raise CliError(
                "empty_query",
                "query must not be blank",
                ExitCode.INVALID_INPUT,
            )
        if args.k <= 0:
            raise CliError("invalid_k", "k must be positive", ExitCode.INVALID_INPUT)
        if args.candidate_k is not None and args.candidate_k < args.k:
            raise CliError(
                "invalid_candidate_k",
                "candidate-k must be at least k",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "ingest":
        if args.expected_documents <= 0:
            raise CliError(
                "invalid_expected_documents",
                "expected-documents must be positive",
                ExitCode.INVALID_INPUT,
            )
        if args.chunk_batch_size <= 0:
            raise CliError(
                "invalid_chunk_batch_size",
                "chunk-batch-size must be positive",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "serve":
        if not args.host.strip():
            raise CliError("invalid_host", "host must not be blank", ExitCode.INVALID_INPUT)
        if not 1 <= args.port <= 65_535:
            raise CliError(
                "invalid_port",
                "port must be between 1 and 65535",
                ExitCode.INVALID_INPUT,
            )
        if args.workers <= 0:
            raise CliError(
                "invalid_workers",
                "workers must be positive",
                ExitCode.INVALID_INPUT,
            )


def _provider_settings(settings: Settings, provider: ProviderName) -> Settings:
    return settings.model_copy(update={"embedding_provider": provider})


def _filters(args: argparse.Namespace) -> RetrievalFilters:
    return RetrievalFilters(
        doc_ids=tuple(args.doc_id),
        tickers=tuple(args.ticker),
        fiscal_years=tuple(args.fiscal_year),
        forms=tuple(args.form),
        items=tuple(args.item),
        kinds=tuple(args.kind),
    )


def _evidence_payload(hit: ChunkHit) -> dict[str, object]:
    """Project the same public evidence fields exposed by the HTTP boundary."""
    from app.api.schemas import EvidenceHit

    return EvidenceHit.from_chunk_hit(hit).model_dump(mode="json")
```

**What to look for in the code**

- `_validate_arguments` opens no file and takes no connection. **An invalid command is rejected at zero cost.**
- `_evidence_payload` turns a `ChunkHit` into a dictionary. That shape has to match HTTP's `EvidenceHit` — it is exactly what M5.3 verifies.
- `_filters` moves CLI arguments into `RetrievalFilters`. M2.1's canonicalization runs here too.

### 3. Using the same seam as HTTP

#### Extend `app/cli.py` — command execution

**Learning action — write the field mapping:** note how `_retrieve` uses `RuntimeApiServices`.

<!-- src: app/cli.py::_retrieve,_run_data_command -->
```python
async def _retrieve(args: argparse.Namespace) -> dict[str, object]:
    from app.db.session import Session
    from app.retrieval.embeddings import embed_missing_chunks, get_embedding_provider
    from app.retrieval.service import retrieve

    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    async with Session() as session:
        backfill = None
        if args.embed_missing:
            backfill = await embed_missing_chunks(session, provider)
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            filters=_filters(args),
        )
    return {
        "status": "ok",
        "command": "retrieve",
        "query": args.query,
        "provider": settings.embedding_provider,
        "backfill": asdict(backfill) if backfill is not None else None,
        "hits": [_evidence_payload(hit) for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


def _checked_manifest(path: Path) -> Path:
    if not path.is_file():
        raise CliError(
            "manifest_not_found",
            f"manifest file does not exist: {path}",
            ExitCode.INVALID_FILE,
        )
    return path


async def _ingest(args: argparse.Namespace) -> dict[str, object]:
    from app.db.bootstrap import bootstrap_schema
    from app.db.session import Session, engine
    from app.ingestion.seed import persist_seed_batch, prepare_seed_batch

    manifest = _checked_manifest(args.manifest)
    try:
        batch = prepare_seed_batch(
            manifest,
            expected_documents=args.expected_documents,
        )
    except json.JSONDecodeError as error:
        raise CliError(
            "invalid_manifest_json",
            f"manifest is not valid JSON at line {error.lineno} column {error.colno}",
            ExitCode.INVALID_FILE,
        ) from error
    except UnicodeDecodeError as error:
        raise CliError(
            "invalid_manifest_encoding",
            "manifest must be UTF-8 text",
            ExitCode.INVALID_FILE,
        ) from error
    except FileNotFoundError as error:
        raise CliError(
            "corpus_file_not_found",
            f"corpus file does not exist: {error.filename}",
            ExitCode.INVALID_FILE,
        ) from error
    except ValueError as error:
        raise CliError(
            "invalid_manifest",
            str(error),
            ExitCode.INVALID_FILE,
        ) from error

    if args.create_schema:
        await bootstrap_schema(engine)
    async with Session() as session:
        result = await persist_seed_batch(
            session,
            batch,
            chunk_batch_size=args.chunk_batch_size,
        )
    return {
        "status": "ok",
        "command": "ingest",
        "manifest": str(manifest),
        "documents": result.documents,
        "chunks": result.chunks,
    }


async def _run_data_command(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "retrieve":
        return await _retrieve(args)
    if args.command == "ingest":
        return await _ingest(args)
    raise AssertionError(f"unsupported data command: {args.command}")
```

**What to look for in the code**

- It constructs `RuntimeApiServices` directly — the same object HTTP routes receive by injection. **Two entry paths, one domain entry point.**
- `_checked_manifest` verifies file existence and JSON validity, raising `INVALID_FILE`. That is where it separates from `INVALID_INPUT`.
- `_ingest` supports `--create-schema`. M1.4's bootstrap is exposed through the CLI.

### 4. Where an exception becomes an exit code

#### Complete `app/cli.py` — dispatch and entry point

**Learning action — implement the exception conversion:** implement `main`'s `try/except` layers yourself.

<!-- src: app/cli.py::_serve,entrypoint -->
```python
def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=args.log_level,
    )


def _failure_payload(error: CliError) -> dict[str, object]:
    return {
        "status": "error",
        "error": {
            "code": error.code,
            "message": error.message,
        },
    }


def _write_json(value: dict[str, object], stream: TextIO) -> None:
    json.dump(value, stream, ensure_ascii=False, sort_keys=True)
    stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return a stable process exit code."""
    try:
        args = arguments(argv)
        _validate_arguments(args)
        if args.command == "serve":
            _serve(args)
            return ExitCode.OK
        payload = asyncio.run(_run_data_command(args))
    except CliError as error:
        _write_json(_failure_payload(error), sys.stderr)
        return error.exit_code
    except OpenAIError as error:
        failure = CliError(
            "provider_unavailable",
            f"embedding provider is unavailable ({type(error).__name__})",
            ExitCode.UNAVAILABLE,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code
    except SQLAlchemyError as error:
        failure = CliError(
            "database_unavailable",
            f"database is unavailable ({type(error).__name__})",
            ExitCode.UNAVAILABLE,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code

    _write_json(payload, sys.stdout)
    return ExitCode.OK


def entrypoint() -> None:
    """Run the installed console script without printing a Python traceback."""
    raise SystemExit(main())
```

**What to look for in the code**

- `main` returns an `int`. It never calls `sys.exit`, so a test can call the function directly and inspect the exit code.
- `_failure_payload` emits failure as JSON too. A script parses stdout to read the code.
- `ApiProblemError` is caught and converted to `UNAVAILABLE`. M5.1's 503 becomes exit code 4 in the CLI — the same meaning in a different expression.
- `_serve` is the only place uvicorn is called, and only under the `serve` command, never at import.

Append the module execution guard at the end of the file. Those two lines are what make `python -m app.cli` work.

```python
if __name__ == "__main__":
    entrypoint()
```

### 5. The assembly gets verified separately

M5.1's tests ran against fake services and checked only HTTP shape. M5.2's tests looked at the runtime adapter on its own.

**Both can pass and the two can still behave differently once joined.**

A common example: HTTP emits evidence as `EvidenceHit` while the CLI emits a slightly different shape. Each test passes. Then M6's UI, which uses both paths, breaks there.

So M5.3 **writes no new code and verifies the assembled state.**

- does `/retrieve` really call M2 (not a fake)
- does `/review` go through M2 to reach M4
- do terminal reports really persist
- **do CLI and HTTP emit the same evidence shape**
- are health and OpenAPI exposed

### Health checks must not require a corpus

Notice that `/health` returns only `HealthResponse()`. It does not touch the database.

That is deliberate. A health check answers **"is the process ready to take requests?"**, not "has all the data arrived?"

Make it hit the database and deployment tangles: the container is up but seeding has not finished, so the orchestrator keeps restarting it. The two concerns have to stay separate.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/api/test_06_cli.py tests/api/test_07_runtime.py -q
uv run pytest tests/api/test_08_integration.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| An empty query and a missing file sharing an exit code | A script can tell what needs fixing. |
| A database connection at import time | Test collection and `--help` run without a database. |
| A CLI evidence shape unlike HTTP's | Both entry points tell the same story. |
| A health check that hits the database | A slow seed never creates a restart loop. |
| A paid call running from defaults | Review turns on only when switched on explicitly. |

### What you should be able to explain now

- **What can a script decide because exit codes 2 and 3 are separate?**
  - **Answer:** It can distinguish a command argument that must be fixed from an invalid file that must be repaired or replaced, and choose its next action accordingly.
- **Why does it matter that `_validate_arguments` performs no I/O?**
  - **Answer:** Invalid commands are rejected deterministically at zero file, network, or database cost.
- **What does the CLI using `RuntimeApiServices` directly guarantee?**
  - **Answer:** The current CLI does not use `RuntimeApiServices` for `_retrieve` or `_ingest`; those commands assemble database, retrieval, and ingestion calls directly. It therefore does not by itself guarantee parity with HTTP.
- **Why does `main` not call `sys.exit`?**
  - **Answer:** Tests and other Python callers can invoke it and inspect the integer result without catching `SystemExit`; only `entrypoint` converts it into a process exit.
- **What happens at deployment if the health check hits the database?**
  - **Answer:** Seeding or a temporary database delay marks a healthy process as unready, causing the orchestrator to restart it repeatedly.

---

[← Previous: Runtime assembly](04-runtime.md) · [Module overview](../03-build.md)
