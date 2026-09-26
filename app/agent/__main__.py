"""Command-line acceptance path for the M9 tool-calling agent."""

import argparse
import asyncio
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.provider import DeterministicToolProvider

# Load providers and runtime services only after argument parsing, so `--help`
# works without a valid model or database configuration.

# Parse-time bounds mirror the runtime contracts so a bad value fails as a usage
# error before any settings load: search k mirrors SearchFilingsParams
# (app/agent/builtin_tools.py, gt=0 le=20) and iterations mirror AgentBudget
# (app/agent/types.py, gt=0 le=64). The runtime models remain the authority; the
# demo builds its arguments from the real parameter model, so drift fails loudly.
MAX_SEARCH_K = 20
MAX_ITERATIONS_CEILING = 64


def _bounded_int(name: str, ceiling: int, value: str) -> int:
    """Parse one argparse integer that must lie in ``1..ceiling``."""
    parsed = int(value)
    if not 0 < parsed <= ceiling:
        raise argparse.ArgumentTypeError(f"{name} must be between 1 and {ceiling}")
    return parsed


def _positive_decimal(name: str, value: str) -> Decimal:
    """Parse one finite positive decimal command-line allowance."""
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError(f"{name} must be a decimal") from error
    if not parsed.is_finite() or parsed <= 0:
        raise argparse.ArgumentTypeError(f"{name} must be greater than zero")
    return parsed


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse agent acceptance arguments."""
    parser = argparse.ArgumentParser(description="Run the evidence-checked filing agent.")
    parser.add_argument("--question", help="Nonempty review question.")
    parser.add_argument(
        "--k",
        type=lambda value: _bounded_int("--k", MAX_SEARCH_K, value),
        default=5,
        help="Hits per search tool call when the model or demo omits k.",
    )
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai"),
        default="deterministic",
        help=(
            "deterministic runs an offline two-turn demo that searches and then "
            "answers NOT_IN_DOCS; openai runs the real tool-calling loop."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Policy-approved OpenAI model for --provider openai; "
            "defaults to the agent role's policy default."
        ),
    )
    parser.add_argument(
        "--max-cost-usd",
        type=lambda value: _positive_decimal("--max-cost-usd", value),
        default=Decimal("0.25"),
        help="Cumulative OpenAI cost ceiling for one agent run.",
    )
    parser.add_argument(
        "--max-iterations",
        type=lambda value: _bounded_int("--max-iterations", MAX_ITERATIONS_CEILING, value),
        default=8,
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Serve the tool registry over MCP stdio instead of answering a question.",
    )
    return parser.parse_args(argv)


def _demo_provider(question: str, k: int) -> DeterministicToolProvider:
    """Script the offline demo: one real search, then an honest NOT_IN_DOCS.

    Both scripted calls are built from the real parameter models, so a renamed
    or re-constrained field breaks here at construction instead of surfacing as
    a silent runtime rejection.
    """
    from app.agent.builtin_tools import SearchFilingsParams
    from app.agent.provider import DeterministicToolProvider, ProviderTurn
    from app.agent.types import AgentAnswer, ToolCall

    search_arguments = SearchFilingsParams(query=question, k=k).model_dump_json()
    answer_arguments = AgentAnswer(
        label="NOT_IN_DOCS",
        answer="NOT_IN_DOCS",
        citations=(),
        rationale=(
            "The offline demo provider cannot ground an answer; "
            "run with --provider openai for a real agent run."
        ),
    ).model_dump_json()
    return DeterministicToolProvider(
        [
            ProviderTurn(
                output_text="Searching the corpus for evidence.",
                tool_calls=(
                    ToolCall(
                        call_id="demo-1",
                        name="search_filings",
                        arguments_json=search_arguments,
                    ),
                ),
                input_tokens=0,
                output_tokens=0,
            ),
            ProviderTurn(
                output_text="",
                tool_calls=(
                    ToolCall(
                        call_id="demo-2",
                        name="final_answer",
                        arguments_json=answer_arguments,
                    ),
                ),
                input_tokens=0,
                output_tokens=0,
            ),
        ]
    )


async def _run(args: argparse.Namespace) -> dict[str, object]:
    """Run one agent request over lazily loaded runtime resources.

    Parameters
    ----------
    args : argparse.Namespace
        Validated CLI arguments selecting provider, question, limits, and hit count.

    Returns
    -------
    dict[str, object]
        JSON-compatible terminal ``AgentResult`` payload.

    Notes
    -----
    Database and retrieval modules load only after argument parsing, so ``--help`` and
    package imports remain independent of runtime configuration. Tools open one
    session per call from the process session factory, and the pool behind it is
    released on every exit path, as ``app/cli.py`` does.

    Raises
    ------
    SystemExit
        If ``--provider openai`` is selected but the MODE-selected key slot is
        empty; the slot rule never falls back to another environment's credential.
    """
    from app.agent.builtin_tools import build_default_registry
    from app.agent.loop import run_agent
    from app.agent.provider import OpenAIToolProvider, ToolCallingProvider
    from app.agent.types import AgentBudget
    from app.config import get_settings
    from app.db.session import Session, engine
    from app.retrieval.embeddings import get_embedding_provider

    openai_provider: OpenAIToolProvider | None = None
    provider: ToolCallingProvider
    if args.provider == "openai":
        # The key travels through Settings exactly as it does for every other
        # OpenAI client: MODE selects the slot and a missing slot never falls back.
        settings = get_settings()
        if settings.openai_api_key is None:
            raise SystemExit(
                "--provider openai requires the MODE-selected OpenAI key slot "
                "(OPENAI_API_KEY_LOCAL for MODE=dev, OPENAI_API_KEY_PROD for MODE=prod)"
            )
        openai_provider = OpenAIToolProvider(
            model_name=args.model,
            api_key=settings.openai_api_key.get_secret_value(),
        )
        provider = openai_provider
    else:
        provider = _demo_provider(args.question, args.k)
    try:
        registry = build_default_registry(
            Session,
            embedding_provider=get_embedding_provider(),
            search_k=args.k,
        )
        result = await run_agent(
            args.question,
            registry=registry,
            provider=provider,
            budget=AgentBudget(
                max_iterations=args.max_iterations,
                max_total_cost_usd=args.max_cost_usd,
            ),
        )
    finally:
        if openai_provider is not None:
            await openai_provider.aclose()
        await engine.dispose()
    return result.model_dump(mode="json")


async def _serve_mcp() -> None:
    """Serve the registry tools over MCP stdio with per-call sessions."""
    from app.agent.builtin_tools import build_default_registry
    from app.agent.mcp_server import serve_stdio
    from app.db.session import Session, engine
    from app.retrieval.embeddings import get_embedding_provider

    try:
        registry = build_default_registry(
            Session,
            embedding_provider=get_embedding_provider(),
        )
        await serve_stdio(registry)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    """Run the M9 acceptance command and print machine-readable evidence.

    Raises
    ------
    SystemExit
        With a usage message when no nonblank question was supplied outside MCP
        mode — checked before any runtime module loads — and with exit code 1
        when the run ends in a terminal failure status, so scripts gating on the
        exit code cannot mistake ``provider_error`` or ``budget_exceeded`` for a
        grounded answer.
    """
    args = arguments(argv)
    if args.mcp:
        asyncio.run(_serve_mcp())
        return
    if not args.question or not args.question.strip():
        raise SystemExit("--question is required unless --mcp is set")
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
