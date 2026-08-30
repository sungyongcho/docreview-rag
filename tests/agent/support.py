"""Builders shared by the agent tests."""

from app.agent.provider import ProviderTurn


def turn(**changes):
    """Build one provider turn with optional field replacements."""
    values = {
        "output_text": "",
        "tool_calls": (),
        "input_tokens": 10,
        "output_tokens": 5,
    }
    values.update(changes)
    return ProviderTurn(**values)
