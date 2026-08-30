"""Command-line acceptance path for the M9 tool-calling agent."""

import argparse
import asyncio
from collections.abc import Sequence
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.provider import DeterministicToolProvider

# Imported inside the functions that need them, never at module scope: the agent
# types reach app.retrieval, whose package import pulls in the database models and
# with them the settings. `--help` must answer without a valid configuration, the
# same way app/cli.py does.


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse agent acceptance arguments."""
    parser = argparse.ArgumentParser(description="Run the evidence-checked filing agent.")
    parser.add_argument("--question", help="Nonempty review question.")
    parser.add_argument("--k", type=int, default=5, help="Hits per search tool call.")
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai"),
        default="deterministic",
        help=(
            "deterministic runs an offline two-turn demo that searches and then "
            "answers NOT_IN_DOCS; openai runs the real tool-calling loop."
        ),
    )
    parser.add_argument("--model", default="gpt-5-mini", help="OpenAI model for --provider openai.")
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Serve the tool registry over MCP stdio instead of answering a question.",
    )
    return parser.parse_args(argv)


def _demo_provider(question: str, k: int) -> DeterministicToolProvider:
    """Script the offline demo: one real search, then an honest NOT_IN_DOCS."""
    from app.agent.provider import DeterministicToolProvider, ProviderTurn
    from app.agent.types import ToolCall

    search_arguments = json.dumps(
        {"query": question, "k": k, "issuers": None, "fiscal_years": None, "forms": None}
    )
    answer_arguments = json.dumps(
        {
            "label": "NOT_IN_DOCS",
            "answer": "NOT_IN_DOCS",
            "citations": [],
            "rationale": (
                "The offline demo provider cannot ground an answer; "
                "run with --provider openai for a real agent run."
            ),
        }
    )
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

    Raises
    ------
    SystemExit
        If no nonblank question was supplied outside MCP mode.

    Notes
    -----
    Database and retrieval modules load only after argument parsing, so ``--help`` and
    package imports remain independent of runtime configuration.
    """
    from app.agent.builtin_tools import build_default_registry
    from app.agent.loop import run_agent
    from app.agent.provider import OpenAIToolProvider, ToolCallingProvider
    from app.agent.types import AgentBudget
    from app.db.session import Session
    from app.retrieval.embeddings import get_embedding_provider

    if not args.question or not args.question.strip():
        raise SystemExit("--question is required unless --mcp is set")
    async with Session() as session:
        registry = build_default_registry(
            session,
            embedding_provider=get_embedding_provider(),
        )
        provider: ToolCallingProvider
        if args.provider == "openai":
            provider = OpenAIToolProvider(model_name=args.model)
        else:
            provider = _demo_provider(args.question, args.k)
        result = await run_agent(
            args.question,
            registry=registry,
            provider=provider,
            budget=AgentBudget(max_iterations=args.max_iterations),
        )
    return result.model_dump(mode="json")


async def _serve_mcp() -> None:
    """Serve the registry tools over MCP stdio with one live session."""
    from app.agent.builtin_tools import build_default_registry
    from app.agent.mcp_server import serve_stdio
    from app.db.session import Session
    from app.retrieval.embeddings import get_embedding_provider

    async with Session() as session:
        registry = build_default_registry(
            session,
            embedding_provider=get_embedding_provider(),
        )
        await serve_stdio(registry)


def main() -> None:
    """Run the M9 acceptance command and print machine-readable evidence."""
    args = arguments()
    if args.mcp:
        asyncio.run(_serve_mcp())
        return
    print(json.dumps(asyncio.run(_run(args)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
