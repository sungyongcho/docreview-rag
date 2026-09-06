# M9 Specification — Bounded tool-calling agent

## Scope

One hand-rolled agent loop over typed tools, offline-testable end to end, with the loop, the registry, and every contract owned by this repository. No agent framework is used; orchestration libraries are out of scope by design.

## Contracts

- `AgentAnswer` carries the M4 label contract: `SUPPORTED` requires citations, `NOT_IN_DOCS` forbids them, and the two states are mutually exclusive.
- A final answer may cite only chunk ids that a tool returned earlier in the same run. The loop tracks evidence through each tool's `evidence_ids` extractor and rejects anything else with an explicit observation.
- `AgentResult` is terminal and exclusive: `ok` runs carry an answer and no failure; every other status carries a failure and no answer.
- Every iteration is recorded as an `AgentStep` with its tool calls, observations, and `StepUsage` (model, endpoint, tokens, latency, retries).

## The loop

- One iteration is one provider turn followed by explicit observations for every requested tool call.
- Tool failures — unknown name, invalid arguments, raised exceptions, non-JSON payloads — become observations the model can read. Silent failures are forbidden.
- A turn with no tool call receives an explicit nudge and costs one iteration.
- `AgentBudget` limits iterations and cumulative tokens. Budgets fail closed: an exhausted run returns `budget_exceeded` with its full step history, never a partial answer.
- Provider exceptions return `provider_error` with the steps completed so far.

## Tools

- A `Tool` is a name, a description, a Pydantic parameters model, an async runner, and an optional evidence extractor.
- The registry rejects duplicate names and the reserved `final_answer`, and generates three synchronized surfaces: strict function specs for the LLM, input schemas for MCP, and a prompt manual.
- Built-in tools wrap M2 retrieval only: `search_filings`, `fetch_chunk`, `compare_years`. Retrieval semantics stay in `app/retrieval`.

## Decomposition

- `decompose_query` asks the M4 provider for one to four unique sub-questions and falls back to the original question on any provider failure.
- `make_decomposed_retriever` returns a callable matching M3's `Retriever` contract; sub-question rankings merge with reciprocal-rank fusion generalized to n lists.
- `run_decomposition_comparison` evaluates baseline and decomposed retrievers through the unmodified M3 harness and reports per-category metrics and deltas.

## Interfaces

- `python -m app.agent --question ...` runs one agent request and prints a JSON `AgentResult`; `--provider deterministic` is an offline demo, `--provider openai` is the real loop.
- `python -m app.agent --mcp` serves the registry over MCP stdio; published schemas equal the registry's strict specs byte for byte.

## Out of scope

- Code-generating agents and sandboxed execution. Running model-written code is a separate safety project with its own isolation requirements; this module's agent calls typed tools only.
- Multi-provider benchmarking. Usage accounting exists per step, but a model-comparison report is future work.
