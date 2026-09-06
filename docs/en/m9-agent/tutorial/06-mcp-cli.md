# M9.6 Tutorial 6 — One contract, exposed twice

The registry already serves the in-process loop. This document exposes the same registry to the outside world — over MCP for external clients, over a CLI for acceptance — and the entire design constraint is sameness: **an external MCP client and the in-process LLM must see the identical tool contract, byte for byte, or "the agent's tools" stops being one auditable thing.**

**Prerequisite:** M9.5 is complete and `uv run pytest tests/agent/test_06_decompose.py -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `build_mcp_server` | **Implement** the protocol bridge | The server owns wire framing; the registry owns meaning |
| The CLI | **Implement** the acceptance surface | JSON evidence, M2's convention |
| The offline demo | **Review the honesty constraint** | A scripted provider cannot claim evidence |

### 1. The MCP bridge publishes, it does not define

#### Create `app/agent/mcp_server.py` — the server

**Learning action — implement the protocol bridge:** find every place a schema or a result shape originates, and confirm none of them is this file.

<!-- src: app/agent/mcp_server.py::build_mcp_server,serve_stdio -->
```python
def build_mcp_server(registry: ToolRegistry) -> Server:
    """Build one MCP server whose tool list mirrors the registry exactly.

    The input schemas come from the same strict transform the agent loop sends
    to the LLM, so an MCP client and the in-process agent see one contract.
    Tool failures come back as ``is_error`` results with a readable message —
    the same explicit-observation rule the loop applies.
    """
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    server: Server = Server(SERVER_NAME)

    async def list_tools(
        context: ServerRequestContext[Any],
        params: mcp_types.PaginatedRequestParams,
    ) -> mcp_types.ListToolsResult:
        del context, params
        return mcp_types.ListToolsResult(
            tools=[
                mcp_types.Tool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=dict(strict_response_format(tool.parameters)["schema"]),
                )
                for tool in registry.tools
            ]
        )

    async def call_tool(
        context: ServerRequestContext[Any],
        params: mcp_types.CallToolRequestParams,
    ) -> mcp_types.CallToolResult:
        del context
        try:
            tool = registry.get(params.name)
            parameters = tool.parameters.model_validate(params.arguments or {})
            output = await tool.run(parameters)
            payload = json.dumps(output, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        except (ValueError, ValidationError) as error:
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(error))],
                is_error=True,
            )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=payload)],
            is_error=False,
        )

    server.add_request_handler("tools/list", mcp_types.PaginatedRequestParams, list_tools)
    server.add_request_handler("tools/call", mcp_types.CallToolRequestParams, call_tool)
    return server


async def serve_stdio(registry: ToolRegistry) -> None:
    """Run the registry-backed MCP server over stdio until the client closes it."""
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
```

**What to look for in the code**

- `tools/list` builds each MCP `Tool` through the same `strict_response_format` call that `registry.specs()` uses — **the published `input_schema` is the very schema the LLM receives, derived from the same declaration, so drift between the two consumers is structurally impossible.**
- `tools/call` reuses the registry's validation and runner path. Tool errors come back as `is_error=True` results with text — MCP's spelling of the loop's own rule that failures are data.
- The low-level `Server` with explicit request handlers was a deliberate choice over the high-level decorators: this module's whole claim is schema fidelity, so the bridge publishes existing schemas rather than letting a framework re-derive them.

### 2. Acceptance is a command that prints evidence

#### Create `app/agent/__main__.py` — the CLI

**Learning action — implement the acceptance surface:** compare the flags and the output discipline with `python -m app.retrieval` from M2.

<!-- src: app/agent/__main__.py::arguments,main -->
```python
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
    search_arguments = json.dumps(
        {"query": question, "k": k, "tickers": None, "fiscal_years": None, "forms": None}
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
    """Run one agent request over a live database session."""
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
```

**What to look for in the code**

- One command, machine-readable output: `python -m app.agent --question ...` prints a JSON `AgentResult` with every step, observation, and token count. A reviewer replays the run from the printout alone.
- `--provider deterministic` runs the demo offline; `--provider openai` runs the live loop; `--mcp` serves stdio. Three modes, one registry underneath.
- The deterministic script drives a real search against the real corpus, then finishes with `NOT_IN_DOCS`. **A scripted provider cannot know which chunk ids the live search returned, so the only answer it can honestly finish with is the empty one — the demo obeys the same evidence gate as production** (bug B4 is the version that didn't).

### Focused tests and the contract they keep

```bash
uv run pytest tests/agent/test_07_mcp_cli.py -q
```

| What the test breaks | Contract it protects |
|---|---|
| An MCP tool list diverging from `registry.specs()` | One contract, both consumers, byte for byte |
| A tool failure crossing MCP as an exception | Failures are `is_error` results, still data |
| A CLI run without JSON evidence | Acceptance output stays machine-checkable |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why must the MCP schemas equal `registry.specs()` exactly?**
  - **Answer:** Two consumers with two schema derivations will drift; publishing the one existing schema makes divergence impossible rather than merely tested-against.
- **Why does the offline demo answer `NOT_IN_DOCS`?**
  - **Answer:** The scripted provider cannot have seen the live search's chunk ids, so any cited answer would be fabricated evidence — the demo submits to the same gate as production.
- **What did the CLI inherit from M2?**
  - **Answer:** The acceptance convention: one command, JSON evidence a reviewer can verify without trusting the author's prose.

### Where the module ends

Two roads deliberately not taken: a code-executing agent (model-written code needs sandbox isolation — a separate safety project, not a checkpoint) and a multi-provider benchmark report (the per-step usage accounting is ready for it; the report is future work). The module hands every future surface a single consumable: `AgentResult`, a run that explains itself.

---

[← Previous: decomposition](05-decomposition.md) · [Module overview](../03-build.md) · [Verification](../05-verify.md)
