"""M9.1 tool registry: registration rules, strict specs, and the generated manual."""

from pydantic import BaseModel, ConfigDict, Field
import pytest

from app.agent.registry import ToolRegistry
from app.agent.tools import Tool


class EchoParams(BaseModel):
    """Closed argument schema for the echo tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)


def echo_tool(*, name="echo_text"):
    """Build one echo tool, optionally under a different name."""

    async def run(params):
        """Return the text it was given."""
        return {"text": params.text}

    return Tool(
        name=name,
        description="Echo one nonblank text argument.",
        parameters=EchoParams,
        run=run,
    )


def test_tool_rejects_bad_identity_and_reserved_names():
    """Reject a name that is not snake case, and the reserved final answer."""
    with pytest.raises(ValueError, match="snake_case"):
        echo_tool(name="Echo-Text")
    with pytest.raises(ValueError, match="reserved"):
        echo_tool(name="final_answer")


def test_registry_rejects_duplicates_and_names_the_known_tools():
    """Reject a duplicate registration and name an unknown tool in the error."""
    registry = ToolRegistry()
    registry.register(echo_tool())

    with pytest.raises(ValueError, match="duplicate tool name"):
        registry.register(echo_tool())
    with pytest.raises(ValueError, match="unknown tool: missing"):
        registry.get("missing")
    assert registry.names == ("echo_text",)


def test_specs_publish_strict_closed_schemas():
    """Publish each tool as a strict function schema that admits no extra field."""
    registry = ToolRegistry()
    registry.register(echo_tool())

    (spec,) = registry.specs()
    assert spec["type"] == "function"
    assert spec["name"] == "echo_text"
    assert spec["strict"] is True
    assert spec["parameters"]["additionalProperties"] is False
    assert spec["parameters"]["required"] == ["text"]


def test_manual_names_every_tool_and_argument():
    """Name every tool with its arguments and description in the manual."""
    registry = ToolRegistry()
    registry.register(echo_tool())

    manual = registry.manual()
    assert "echo_text(text)" in manual
    assert "Echo one nonblank text argument." in manual
