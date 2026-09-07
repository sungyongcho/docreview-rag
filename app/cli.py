"""Deterministic command-line entrypoints for retrieval, ingestion, and serving."""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from enum import IntEnum
import json
import sys
from typing import TYPE_CHECKING, Literal, TextIO
from urllib.parse import urlsplit

import httpx
from openai import OpenAIError
from pydantic import ValidationError
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
    """Declare the retrieve command and every ranking knob it forwards."""
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
        choices=("deterministic", "openai", "sbert"),
        default=None,
        help="Embedding provider override; the configured EMBEDDING_PROVIDER otherwise.",
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval; requires an explicit --provider.",
    )
    parser.add_argument("--doc-id", action="append", default=[], help="Exact document filter.")
    parser.add_argument("--issuer", action="append", default=[], help="Exact issuer filter.")
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
    """Declare ingestion through the shared application job API."""
    parser = subparsers.add_parser(
        "ingest",
        help="Queue parsing and chunking; run embeddings and BM25 separately.",
        description="Parse and store selected sources. Then run rag-corpus backfill_embeddings "
        "and rag-corpus rebuild_bm25 before hybrid retrieval.",
    )
    parser.add_argument("--manifest", required=True, help="Corpus-relative manifest name.")
    parser.add_argument("--selection", required=True, help="Explicit processing selection ID.")
    parser.add_argument("--expected-documents", type=int, default=None)
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000/docreview-rag-agent/api/admin",
        help="Development administrator API base URL.",
    )


def _add_serve_parser(subparsers: Subparsers) -> None:
    """Declare the serve command and the bind options it hands to the server."""
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
    """Reject the argument combinations argparse cannot express, as typed exits."""
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
        # Chunks carry no embedding-provenance column, so a backfill with an implicit
        # provider could silently commit mixed-provider vectors into one vector space.
        if args.embed_missing and args.provider is None:
            raise CliError(
                "embed_missing_requires_provider",
                "pass --provider explicitly when backfilling embeddings",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "ingest":
        if args.expected_documents is not None and args.expected_documents <= 0:
            raise CliError(
                "invalid_expected_documents",
                "expected-documents must be positive",
                ExitCode.INVALID_INPUT,
            )


def _provider_settings(settings: Settings, provider: ProviderName | None) -> Settings:
    """Re-validate the settings with the explicitly requested embedding provider.

    ``model_copy(update=...)`` would skip model validators — and with them the
    fail-closed OpenAI key guard — so the override goes through full validation.
    """
    if provider is None:
        return settings
    return Settings.model_validate({**settings.model_dump(), "embedding_provider": provider})


def _filters(args: argparse.Namespace) -> RetrievalFilters:
    """Build the retrieval filters from the repeatable narrowing options."""
    from app.retrieval.types import RetrievalFilters

    return RetrievalFilters(
        doc_ids=tuple(args.doc_id),
        issuers=tuple(args.issuer),
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
    """Retrieve cited evidence with the same ranking plan the configuration measured."""
    from app.db.session import Session
    from app.ingestion.progress import OperationProgress, operation_bar
    from app.retrieval.embeddings import (
        EmbeddingBackfillResult,
        OpenAIEmbeddingProvider,
        embed_missing_chunks,
        get_embedding_provider,
    )
    from app.retrieval.service import retrieve

    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    async with Session() as session:
        backfill = None
        if args.embed_missing:
            with operation_bar("Embeddings", unit="batch") as progress:
                progress(OperationProgress("embedding", 0, None, "Selecting missing chunks"))

                def on_batch(result: EmbeddingBackfillResult) -> None:
                    """Publish cumulative embedding batches without exposing provider detail."""
                    progress(
                        OperationProgress(
                            "embedding",
                            result.batches,
                            None,
                            f"{result.embedded} chunks stored",
                        )
                    )

                backfill = await embed_missing_chunks(session, provider, on_batch=on_batch)
                progress(
                    OperationProgress(
                        "embedding",
                        backfill.batches,
                        backfill.batches,
                        f"{backfill.embedded} chunks stored",
                    )
                )
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            filters=_filters(args),
            route_by_language=settings.query_language_routing,
            lexical_ranker=settings.lexical_ranker,
            bm25_k1=settings.bm25_k1,
            bm25_b=settings.bm25_b,
            bm25_idf=settings.bm25_idf,
        )
    return {
        "status": "ok",
        "command": "retrieve",
        "query": args.query,
        "provider": settings.embedding_provider,
        "backfill": asdict(backfill) if backfill is not None else None,
        "embedding_usage": (
            {
                "requests": provider.usage.requests,
                "input_tokens": provider.usage.input_tokens,
                "estimated_cost_usd": format(provider.usage.estimated_cost_usd, "f"),
            }
            if isinstance(provider, OpenAIEmbeddingProvider)
            else None
        ),
        "hits": [_evidence_payload(hit) for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


async def _ingest(args: argparse.Namespace) -> dict[str, object]:
    """Submit the same typed ingestion job used by the development web client."""
    from app.api.admin_schemas import CorpusJobResource, CorpusOperationRequest

    request = CorpusOperationRequest(
        kind="ingest_manifest",
        manifest=args.manifest,
        selection_id=args.selection,
        expected_documents=args.expected_documents,
    )
    parsed = urlsplit(args.api_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.post(
                args.api_url.rstrip("/") + "/corpus/jobs/",
                json=request.model_dump(mode="json"),
                headers={"Origin": origin},
            )
            response.raise_for_status()
            job = CorpusJobResource.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as error:
        raise CliError(
            "ingestion_job_unavailable",
            "Check the development Jobs panel before retrying; the request may have been accepted.",
            ExitCode.UNAVAILABLE,
        ) from error
    return job.model_dump(mode="json")


async def _run_data_command(args: argparse.Namespace) -> dict[str, object]:
    """Dispatch to the command that needs a database session, then release the pool."""
    if args.command == "ingest":
        return await _ingest(args)
    from app.db.session import engine

    try:
        if args.command == "retrieve":
            return await _retrieve(args)
        raise AssertionError(f"unsupported data command: {args.command}")
    finally:
        await engine.dispose()


def _serve(args: argparse.Namespace) -> None:
    """Hand the bind options to the server; this call does not return."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=args.log_level,
    )


def _failure_payload(error: CliError) -> dict[str, object]:
    """Shape one typed failure into the envelope every command prints."""
    return {
        "status": "error",
        "error": {
            "code": error.code,
            "message": error.message,
        },
    }


def _write_json(value: dict[str, object], stream: TextIO) -> None:
    """Write one payload as stable, sorted, newline-terminated JSON."""
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
    except ValidationError as error:
        # Environment settings failed validation. The default rendering would echo
        # every input value — including loaded credentials — so only locations and
        # messages cross into the error envelope.
        issues = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or 'settings'}: {issue['msg']}"
            for issue in error.errors(include_url=False, include_input=False)
        )
        failure = CliError(
            "invalid_configuration",
            f"configuration is invalid ({issues})",
            ExitCode.INVALID_INPUT,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code
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
