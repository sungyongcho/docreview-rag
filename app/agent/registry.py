"""Tool registry that publishes one schema to the LLM, the MCP server, and the prompt."""

from typing import Any

from app.agent.tools import Tool
from app.llm import strict_response_format


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
