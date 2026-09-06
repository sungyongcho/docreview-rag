"""Tool registry that publishes one schema to the LLM, the MCP server, and the prompt."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any

from pydantic import ValidationError

from app.agent.tools import Tool, ToolError, safe_runtime_error
from app.llm.provider import strict_response_format, validation_errors


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
    :class:`~app.agent.tools.ToolError` and a validation failure carry their
    model-actionable detail verbatim — both are authored against the caller's
    own input, never against provider payloads — while every unexpected
    exception is redacted through :func:`~app.agent.tools.safe_runtime_error`.
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
