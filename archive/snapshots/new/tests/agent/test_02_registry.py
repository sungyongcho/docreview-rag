"""M9.1 tool registry: registration rules, strict specs, and the generated manual."""

from pydantic import BaseModel, ConfigDict, Field
import pytest

from tests.support import need


class EchoParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)


def echo_tool(AG, *, name="echo_text"):
    async def run(params):
        return {"text": params.text}

    return AG.Tool(
        name=name,
        description="Echo one nonblank text argument.",
        parameters=EchoParams,
        run=run,
    )


def test_tool_rejects_bad_identity_and_reserved_names(AG):
    need(AG, "Tool")
    with pytest.raises(ValueError, match="snake_case"):
        echo_tool(AG, name="Echo-Text")
    with pytest.raises(ValueError, match="reserved"):
        echo_tool(AG, name="final_answer")


def test_registry_rejects_duplicates_and_names_the_known_tools(AG):
    need(AG, "ToolRegistry")
    registry = AG.ToolRegistry()
    registry.register(echo_tool(AG))

    with pytest.raises(ValueError, match="duplicate tool name"):
        registry.register(echo_tool(AG))
    with pytest.raises(ValueError, match="unknown tool: missing"):
        registry.get("missing")
    assert registry.names == ("echo_text",)


def test_specs_publish_strict_closed_schemas(AG):
    need(AG, "ToolRegistry")
    registry = AG.ToolRegistry()
    registry.register(echo_tool(AG))

    (spec,) = registry.specs()
    assert spec["type"] == "function"
    assert spec["name"] == "echo_text"
    assert spec["strict"] is True
    assert spec["parameters"]["additionalProperties"] is False
    assert spec["parameters"]["required"] == ["text"]


def test_manual_names_every_tool_and_argument(AG):
    need(AG, "ToolRegistry")
    registry = AG.ToolRegistry()
    registry.register(echo_tool(AG))

    manual = registry.manual()
    assert "echo_text(text)" in manual
    assert "Echo one nonblank text argument." in manual
