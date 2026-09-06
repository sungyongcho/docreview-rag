# M9.1 Tutorial 1 — Contracts before autonomy

The agent will choose its own route through the tools. Before a single loop iteration exists, this document fixes what the agent may say and how a tool is declared — because **once the model picks the actions, the only thing standing between a plausible answer and a fabricated one is the set of states the types refuse to represent.**

**Prerequisite:** M1–M8 are complete and `uv run pytest -o addopts="" tests/workflow -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `ToolCall`, `Observation`, `AgentStep` | **Write the model declarations** | Why an error is an observation, not an exception |
| `AgentAnswer`, `AgentResult` | **Implement** the exclusivity validators | The M4 label contract, enforced again at a new boundary |
| `Tool` and `ToolRegistry` | **Write the structure, then review the surfaces** | One declaration feeding three consumers |

### 1. An error is an observation

The loop will feed every tool result back to the model. A failed call must come back the same way — as data the model can read — so the observation type carries either output or an error, never both and never neither.

#### Create `app/agent/types.py` — calls and observations

**Learning action — write the model declarations:** note which combinations the validator makes unrepresentable.

<!-- src: app/agent/types.py::ToolCall,Observation -->
```python
class ToolCall(StrictAgentModel):
    """One tool invocation requested by the model, with raw JSON arguments."""

    call_id: NonBlank
    name: NonBlank
    arguments_json: StrictStr


class Observation(StrictAgentModel):
    """The explicit result the loop feeds back for one tool call.

    Errors are observations too: a failed call must come back as a typed
    message the model can read, never as a silently dropped step.
    """

    call_id: NonBlank
    name: NonBlank
    output_json: StrictStr = ""
    error: NonBlank | None = None

    @model_validator(mode="after")
    def require_output_or_error(self) -> Self:
        """Keep successful output and typed failure mutually exclusive."""
        if self.error is None and not self.output_json:
            raise ValueError("observations require output_json or an error")
        if self.error is not None and self.output_json:
            raise ValueError("failed observations must not also carry output")
        return self
```

**What to look for in the code**

- `arguments_json` stays a raw string. Parsing happens at dispatch time where a failure can become an observation; parsing here would turn model mistakes into exceptions.
- `Observation.require_output_or_error` makes "silently empty" and "both at once" invalid states. **The model must never be left guessing what happened — and the type system now guarantees the loop cannot forget to tell it.**

### 2. The answer contract survives a new boundary

#### Extend `app/agent/types.py` — the final answer

**Learning action — implement the exclusivity validators:** compare each branch with `AnswerDecision` from M4 before writing it.

<!-- src: app/agent/types.py::AgentCitation,AgentAnswer -->
```python
class AgentCitation(StrictAgentModel):
    """One retrieved chunk the final answer stands on."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    citation: NonBlank


class AgentAnswer(StrictAgentModel):
    """The structured final answer with the M4 label and citation contract."""

    label: Literal["SUPPORTED", "NOT_IN_DOCS"]
    answer: NonBlank
    citations: tuple[AgentCitation, ...]
    rationale: NonBlank

    @model_validator(mode="after")
    def validate_label_contract(self) -> Self:
        """Keep supported and absent answers mutually exclusive."""
        chunk_ids = [citation.chunk_id for citation in self.citations]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("citation chunk ids must be unique")
        if self.label == "SUPPORTED":
            if not self.citations:
                raise ValueError("SUPPORTED answers require at least one citation")
            if self.answer == "NOT_IN_DOCS":
                raise ValueError("SUPPORTED answers require a supported answer")
        else:
            if self.answer != "NOT_IN_DOCS":
                raise ValueError("NOT_IN_DOCS answers must use the NOT_IN_DOCS answer")
            if self.citations:
                raise ValueError("NOT_IN_DOCS answers must not carry citations")
        return self
```

**What to look for in the code**

- The label contract is M4's, verbatim in spirit: **`SUPPORTED` without citations and `NOT_IN_DOCS` with citations are both unrepresentable, so no downstream code ever needs to re-check the combination.**
- Citations name `chunk_id`, `doc_id`, and the human citation — the same provenance every other module carries. Uniqueness is validated here; whether the ids were actually retrieved is the loop's job in tutorial 3.

#### Extend `app/agent/types.py` — the terminal result

<!-- src: app/agent/types.py::AgentResult -->
```python
class AgentResult(StrictAgentModel):
    """One terminal agent run: an answer or a typed failure, never both."""

    status: AgentStatus
    answer: AgentAnswer | None
    failure: NonBlank | None
    iterations: NonnegativeInt
    total_input_tokens: NonnegativeInt
    total_output_tokens: NonnegativeInt
    total_time_seconds: NonnegativeFloat
    steps: tuple[AgentStep, ...]

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        """Keep success and failure states mutually exclusive."""
        if self.status == "ok":
            if self.answer is None or self.failure is not None:
                raise ValueError("successful runs require an answer and no failure")
        else:
            if self.answer is not None or self.failure is None:
                raise ValueError("failed runs require a failure and no answer")
        return self
```

**What to look for in the code**

- `ok` requires an answer and no failure; every other status requires the opposite. A run can end well or end typed — never both, never neither.
- The full `steps` history rides along. A result without its steps would be a score without evidence, and M3 already taught why that is worthless.

### 3. One declaration, three consumers

#### Create `app/agent/tools.py` — the tool boundary

**Learning action — write the structure:** decide what a tool must declare so that the LLM, the MCP server, and the prompt can all be generated from it.

<!-- src: app/agent/tools.py::TOOL_NAME,Tool -->
```python
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_TOOL_NAMES = frozenset({"final_answer"})

type EvidenceExtractor = Callable[[Any], tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class Tool[ParamsT: BaseModel]:
    """One callable capability with a validated parameter schema.

    ``run`` receives the already-validated parameters model and returns any
    JSON-serializable payload. ``evidence_ids`` optionally names the chunk ids
    a payload puts into evidence, so the loop can hold final answers to the
    chunks the run actually saw.
    """

    name: str
    description: str
    parameters: type[ParamsT]
    run: Callable[[ParamsT], Awaitable[Any]]
    evidence_ids: EvidenceExtractor | None = None

    def __post_init__(self) -> None:
        """Reject tools whose identity or schema cannot be published."""
        if TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("tool name must be snake_case ascii")
        if self.name in RESERVED_TOOL_NAMES:
            raise ValueError(f"tool name {self.name!r} is reserved for the agent loop")
        if not self.description.strip():
            raise ValueError("tool description must not be blank")
        if not isinstance(self.parameters, type) or not issubclass(self.parameters, BaseModel):
            raise ValueError("tool parameters must be a Pydantic model class")
```

**What to look for in the code**

- `parameters` is a Pydantic model class, not a hand-written schema. Everything else — function specs, MCP schemas, the manual — derives from it.
- `evidence_ids` is the hook the loop uses to learn which chunk ids a payload put into evidence. A tool without it contributes no citable evidence.
- `final_answer` is reserved: finishing the run is the loop's own primitive, so no registry may ever shadow it with a lookalike tool.

#### Create `app/agent/registry.py` — the registry

**Learning action — review the surfaces:** count the places a tool's schema appears and confirm all of them read from this class.

<!-- src: app/agent/registry.py::ToolRegistry -->
```python
class ToolRegistry:
    """Named, immutable-by-convention collection of agent tools.

    The registry is the single source for three consumers: the provider gets
    strict function specs, the MCP server gets input schemas, and the system
    prompt gets a generated manual. One registration feeds all three, so the
    documentation the model reads can never drift from the schema it must obey.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any]] = {}

    def register(self, tool: Tool[Any]) -> None:
        """Add one tool, rejecting duplicates instead of silently replacing them."""
        if not isinstance(tool, Tool):
            raise TypeError("only Tool values can be registered")
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool[Any]:
        """Return one registered tool or fail with the known names."""
        try:
            return self._tools[name]
        except KeyError:
            known = ", ".join(self.names) or "none"
            raise ValueError(f"unknown tool: {name} (registered: {known})") from None

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered tool names in deterministic order."""
        return tuple(sorted(self._tools))

    @property
    def tools(self) -> tuple[Tool[Any], ...]:
        """Return registered tools in deterministic name order."""
        return tuple(self._tools[name] for name in self.names)

    def specs(self) -> list[dict[str, Any]]:
        """Return strict Responses-API function specs for every tool."""
        specs: list[dict[str, Any]] = []
        for tool in self.tools:
            payload = strict_response_format(tool.parameters)
            specs.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": payload["schema"],
                    "strict": True,
                }
            )
        return specs

    def manual(self) -> str:
        """Render the tool manual the system prompt feeds to the model."""
        lines = ["Available tools:"]
        for tool in self.tools:
            properties = tool.parameters.model_json_schema().get("properties", {})
            arguments = ", ".join(sorted(properties)) or "no arguments"
            lines.append(f"- {tool.name}({arguments}): {tool.description}")
        return "\n".join(lines)
```

**What to look for in the code**

- Duplicates are rejected, not replaced. A silent replacement would let two modules fight over one name and the loser would never know.
- `specs()` reuses `strict_response_format` from M4.4 — **the same strict transform that constrains completions now constrains tool arguments, so one schema discipline covers both boundaries.**
- `manual()` is generated. The documentation the model reads cannot drift from the schema it must obey, because both come from the same declaration.

### Focused tests and the contract they keep

```bash
uv run pytest tests/agent/test_01_contracts.py tests/agent/test_02_registry.py -q
```

| What the test breaks | Contract it protects |
|---|---|
| An observation with output and error at once | Failure and success stay mutually exclusive |
| An observation answering a call the step never made | Step provenance cannot be fabricated |
| `SUPPORTED` without citations | The M4 label contract holds at the agent boundary |
| A result with an answer and a failure | Terminal states are exclusive |
| A duplicate or reserved tool name | The registry stays a single honest namespace |
| An open or defaulted parameters schema | Only strictly enforceable tools can be published |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why is a failed tool call an observation instead of an exception?**
  - **Answer:** The model can only correct what it can read; an exception ends the run, an observation teaches the next step.
- **Why does the answer contract repeat M4's label rules?**
  - **Answer:** The agent is a new boundary where fabricated support could enter; making the invalid combinations unrepresentable removes the check from every consumer.
- **What breaks if the manual is written by hand?**
  - **Answer:** The manual and the schema drift, and the model starts calling tools that do not exist or with arguments the schema rejects.

---

[Module overview](../03-build.md) · [Next: providers →](02-providers.md)
