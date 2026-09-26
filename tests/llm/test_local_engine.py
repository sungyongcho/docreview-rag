"""Protocol resolution for the optional local engine and its default timeout."""

import pytest

from app.llm.local_engine import resolve_local_protocol
from app.settings_sources import DEFAULT_LOCAL_TIMEOUT_S


@pytest.mark.parametrize(
    ("base_url", "configured", "expected"),
    [
        ("http://ollama:11434", "auto", "ollama"),
        ("http://host:8000/v1", "auto", "openai_responses"),
        ("http://host:8000/v1/", "auto", "openai_responses"),
        ("http://ollama:11434", "openai_responses", "openai_responses"),
        ("http://host:8000/v1", "ollama", "ollama"),
    ],
)
def test_auto_reads_the_v1_suffix_and_an_explicit_protocol_always_wins(
    base_url: str, configured: str, expected: str
) -> None:
    """The `/v1` suffix is the only signal `auto` has, and it never overrides a choice."""
    assert resolve_local_protocol(base_url, configured) == expected


def test_default_timeout_leaves_room_for_a_slow_first_token() -> None:
    """30 seconds was not enough for structured output on a CPU host; the default is not that."""
    assert DEFAULT_LOCAL_TIMEOUT_S >= 120.0
