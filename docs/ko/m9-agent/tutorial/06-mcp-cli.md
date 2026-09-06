# M9.6 튜토리얼 6 — 하나의 계약을 두 번 노출한다

레지스트리는 이미 인프로세스 루프를 서빙한다. 이 문서는 같은 레지스트리를 바깥 세계에 노출한다 — 외부 클라이언트에는 MCP로, 인수에는 CLI로 — 그리고 설계 제약 전체가 같음이다: **외부 MCP 클라이언트와 인프로세스 LLM은 동일한 도구 계약을 바이트 단위로 봐야 하고, 아니면 "에이전트의 도구"는 감사 가능한 하나이기를 멈춘다.**

**선행 조건:** M9.5 완료, `uv run pytest tests/agent/test_06_decompose.py -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| `build_mcp_server` | 프로토콜 브리지를 **구현한다** | 서버는 와이어 프레이밍을, 레지스트리는 의미를 소유한다 |
| CLI | 인수 표면을 **구현한다** | JSON 증거, M2의 관례 |
| 오프라인 데모 | 정직성 제약을 **검토한다** | 스크립트된 provider는 근거를 주장할 수 없다 |

### 1. MCP 브리지는 발행할 뿐, 정의하지 않는다

#### `app/agent/mcp_server.py` 생성 — 서버

**학습 행동 — 프로토콜 브리지를 구현한다:** 스키마나 결과 형태가 태어나는 모든 곳을 찾고, 그중 어느 곳도 이 파일이 아님을 확인한다.

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

**코드에서 꼭 볼 것**

- `tools/list`는 각 MCP `Tool`을 같은 `strict_response_format` 호출 — `registry.specs()`가 쓰는 바로 그것 — 로 만든다 — **발행되는 `input_schema`는 LLM이 받는 바로 그 스키마이고 같은 선언에서 파생되므로, 두 소비자 사이의 어긋남은 구조적으로 불가능하다.**
- `tools/call`은 레지스트리의 검증·실행 경로를 재사용한다. 도구 에러는 텍스트가 담긴 `is_error=True` 결과로 돌아온다 — 실패는 데이터라는 루프 자신의 규칙을 MCP 철자로 쓴 것이다.
- 명시적 요청 핸들러를 가진 저수준 `Server`는 고수준 데코레이터 대신 일부러 고른 선택이다: 이 모듈의 주장 전체가 스키마 충실도이므로, 브리지는 프레임워크가 스키마를 재유도하게 두지 않고 기존 스키마를 발행한다.

### 2. 인수는 증거를 출력하는 명령이다

#### `app/agent/__main__.py` 생성 — CLI

**학습 행동 — 인수 표면을 구현한다:** 플래그와 출력 규율을 M2의 `python -m app.retrieval`과 비교한다.

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

**코드에서 꼭 볼 것**

- 명령 하나, 기계가 읽는 출력: `python -m app.agent --question ...`은 모든 스텝·관찰·토큰 수를 담은 JSON `AgentResult`를 출력한다. 리뷰어는 출력물만으로 실행을 재생한다.
- `--provider deterministic`은 오프라인 데모를, `--provider openai`는 라이브 루프를 돌리고, `--mcp`는 stdio를 서빙한다. 세 모드, 그 아래 레지스트리는 하나다.
- 결정론적 스크립트는 실제 코퍼스에 실제 검색을 한 번 몰고 간 뒤 `NOT_IN_DOCS`로 마친다. **스크립트된 provider는 라이브 검색이 어떤 chunk id를 돌려줬는지 알 수 없으므로, 정직하게 마칠 수 있는 유일한 답은 빈 답이다 — 데모도 프로덕션과 같은 근거 게이트를 따른다** (그러지 않았던 버전이 버그 B4다).

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/agent/test_07_mcp_cli.py -q
```

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| `registry.specs()`와 어긋나는 MCP 도구 목록 | 하나의 계약, 두 소비자, 바이트 단위로 |
| 예외로 MCP를 건너는 도구 실패 | 실패는 `is_error` 결과, 여전히 데이터다 |
| JSON 증거 없는 CLI 실행 | 인수 출력은 기계 검증 가능하게 남는다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **MCP 스키마는 왜 `registry.specs()`와 정확히 같아야 하는가?**
  - **답:** 스키마 유도가 둘이면 두 소비자는 반드시 어긋난다. 존재하는 하나의 스키마를 발행하면 어긋남은 테스트로 막는 것이 아니라 불가능해진다.
- **오프라인 데모는 왜 `NOT_IN_DOCS`로 답하는가?**
  - **답:** 스크립트된 provider는 라이브 검색의 chunk id를 봤을 리 없으므로, 인용된 답은 무엇이든 조작된 근거다 — 데모도 프로덕션과 같은 게이트에 복종한다.
- **CLI는 M2에서 무엇을 물려받았는가?**
  - **답:** 인수 관례다: 명령 하나, 저자의 산문을 믿지 않고도 리뷰어가 검증할 수 있는 JSON 증거.

### 모듈이 끝나는 곳

일부러 가지 않은 두 길: 코드 실행 에이전트(모델이 쓴 코드는 샌드박스 격리가 필요하다 — 체크포인트가 아니라 별도의 안전 프로젝트다)와 멀티 provider 벤치마크 리포트(스텝별 사용량 기록은 준비돼 있고, 리포트는 이후 과제다). 모듈은 미래의 모든 표면에 소비물 하나를 넘긴다: 스스로를 설명하는 실행, `AgentResult`.

---

[← 이전: 분해](05-decomposition.md) · [모듈 개요](../03-build.md) · [검증](../05-verify.md)
