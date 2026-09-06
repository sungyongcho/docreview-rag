"""Deterministic command-line entrypoints for retrieval, ingestion, and serving."""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from enum import IntEnum
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Literal, TextIO

from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings

if TYPE_CHECKING:
    from app.retrieval.types import ChunkHit, RetrievalFilters

ProviderName = Literal["deterministic", "openai"]


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
        """Raise a typed CLI failure instead of exiting inside argparse."""
        raise CliError("invalid_arguments", message, ExitCode.INVALID_INPUT)


type Subparsers = argparse._SubParsersAction[CliArgumentParser]


def _add_retrieve_parser(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("retrieve", help="Retrieve cited filing evidence.")
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


def _add_ingest_parser(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("ingest", help="Upsert one local corpus manifest.")
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


def _add_serve_parser(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser("serve", help="Run the FastAPI application with Uvicorn.")
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
    """Parse one command without opening files or external services.

    Parameters
    ----------
    argv : Sequence[str] | None
        Explicit arguments, or process arguments when omitted.

    Returns
    -------
    argparse.Namespace
        Parsed retrieve, ingest, or serve command.
    """
    parser = CliArgumentParser(prog="docreview", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_retrieve_parser(subparsers)
    _add_ingest_parser(subparsers)
    _add_serve_parser(subparsers)
    return parser.parse_args(argv)


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
    from app.retrieval.types import RetrievalFilters

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
    """Run one command and return a stable process exit code.

    Parameters
    ----------
    argv : Sequence[str] | None
        Explicit arguments, or process arguments when omitted.

    Returns
    -------
    int
        Stable success, invalid-input, invalid-file, or unavailable exit code.

    Notes
    -----
    Expected failures are emitted as JSON on stderr without credentials or a Python
    traceback. Runtime imports occur only after argument validation.
    """
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


if __name__ == "__main__":
    entrypoint()
