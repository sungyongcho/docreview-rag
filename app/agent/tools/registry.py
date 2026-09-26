"""Tool registry that publishes one schema to the LLM, the MCP server, and the prompt."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.contracts.evidence import EvidenceCitation
from app.llm.decoding import strict_response_format, validation_errors

TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

# The loop owns run termination, so this name is the one contract every tool
# author must not collide with. The loop imports it from here; keeping a second
# literal in loop.py would let the guard and the dispatcher drift apart.
FINAL_ANSWER_NAME = "final_answer"
RESERVED_TOOL_NAMES = frozenset({FINAL_ANSWER_NAME})

type EvidenceExtractor = Callable[[Any], tuple[EvidenceCitation, ...]]


class ToolError(ValueError):
    """Tool-authored failure whose message is safe to show the model.

    Raise this for expected, model-actionable failures — a chunk id the corpus
    does not contain, an unsatisfiable filter. The dispatch layer forwards the
    message verbatim so the model can correct course; every other exception is
    still redacted through :func:`safe_runtime_error`, because an unexpected
    message may embed credentials or provider payloads.
    """


def safe_runtime_error(error: Exception, action: str) -> str:
    """Return a stable public error without copying exception detail or secrets.

    Parameters
    ----------
    error : Exception
        Caught failure whose message may embed credentials or provider payloads.
    action : str
        Short description of the boundary that failed.

    Returns
    -------
    str
        Exception type name and the failed action, with no message text.

    Notes
    -----
    Every surface that reports a caught failure to a model or an MCP client shares
    this projection, so redaction cannot drift between the loop and the server.
    """
    return f"{type(error).__name__}: {action} failed"


@dataclass(frozen=True, slots=True)
class Tool[ParamsT: BaseModel]:
    """One callable capability with a validated parameter schema.

    ``run`` receives the already-validated parameters model and returns any
    JSON-serializable payload. ``evidence_ids`` optionally extracts complete
    immutable chunk identities, so the loop validates more than a forgeable id.
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


class ToolRegistry:
    """Named, immutable-by-convention collection of agent tools.

    The registry is the single source for three consumers: the provider gets
    strict function specs, the MCP server gets tolerant input schemas, and the
    system prompt gets a generated manual. One registration feeds all three, so
    the documentation the model reads can never drift from the schema it must
    obey.
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

    def input_schemas(self) -> list[dict[str, Any]]:
        """Return each tool's name, description, and tolerant JSON input schema.

        Unlike :meth:`specs`, optional fields keep their defaults and stay
        optional, so protocol-neutral consumers such as the MCP server accept an
        idiomatic call that omits them, while the strict provider surface still
        requires every field.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters.model_json_schema(),
            }
            for tool in self.tools
        ]

    def manual(self) -> str:
        """Render the tool manual the system prompt feeds to the model."""
        lines = ["Available tools:"]
        for tool in self.tools:
            properties = tool.parameters.model_json_schema().get("properties", {})
            arguments = ", ".join(sorted(properties)) or "no arguments"
            lines.append(f"- {tool.name}({arguments}): {tool.description}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """Result of one registry-dispatched tool execution.

    Exactly one of ``error`` and ``output_json`` is set. ``output`` carries the
    unserialized payload for consumers that inspect it further, such as the
    loop's evidence extraction.
    """

    output: Any = None
    output_json: str | None = None
    error: str | None = None


async def execute_tool(
    registry: ToolRegistry,
    name: str,
    arguments: Mapping[str, Any],
) -> ToolOutcome:
    """Validate, run, and serialize one registered tool behind the shared error taxonomy.

    Parameters
    ----------
    registry : ToolRegistry
        Single source of executable tools and parameter schemas.
    name : str
        Requested tool name.
    arguments : Mapping[str, Any]
        Already-parsed JSON-object arguments.

    Returns
    -------
    ToolOutcome
        Serialized payload, or a typed error when lookup, validation, execution,
        or serialization fails.

    Notes
    -----
    Both published surfaces — the agent loop and the MCP server — dispatch
    through this function, so their error contracts cannot drift. A
    :class:`~app.agent.tools.registry.ToolError` and a validation failure carry their
    model-actionable detail verbatim — both are authored against the caller's
    own input, never against provider payloads — while every unexpected
    exception is redacted through :func:`~app.agent.tools.registry.safe_runtime_error`.
    """
    try:
        tool = registry.get(name)
    except ValueError as error:
        return ToolOutcome(error=str(error))
    try:
        parameters = tool.parameters.model_validate(dict(arguments))
    except ValidationError as error:
        details = "; ".join(validation_errors(error))
        return ToolOutcome(error=f"invalid arguments for {name}: {details}")
    except ValueError as error:
        return ToolOutcome(error=f"invalid arguments for {name}: {error}")
    try:
        output = await tool.run(parameters)
    except ToolError as error:
        message = str(error).strip() or safe_runtime_error(error, f"tool {name}")
        return ToolOutcome(error=message)
    except Exception as error:
        return ToolOutcome(error=safe_runtime_error(error, f"tool {name}"))
    try:
        output_json = json.dumps(output, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as error:
        return ToolOutcome(error=safe_runtime_error(error, f"tool {name} serialization"))
    return ToolOutcome(output=output, output_json=output_json)
