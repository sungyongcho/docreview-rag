"""Protocol resolution for the optional local engine."""

import pytest

from app.llm.local_engine import resolve_local_protocol


@pytest.mark.parametrize(
    ("base_url", "configured", "expected"),
    [
        pytest.param("http://ollama:11434", "auto", "ollama", id="auto-without-v1-is-ollama"),
        pytest.param(
            "http://host:8000/v1", "auto", "openai_responses", id="auto-with-v1-is-responses"
        ),
        pytest.param(
            "http://host:8000/v1/",
            "auto",
            "openai_responses",
            id="auto-with-v1-and-a-trailing-slash-is-responses",
        ),
        pytest.param("http://host:8000/v1", "ollama", "ollama", id="explicit-protocol-wins"),
    ],
)
def test_auto_reads_the_v1_suffix_and_an_explicit_protocol_always_wins(
    base_url: str, configured: str, expected: str
) -> None:
    """The `/v1` suffix is the only signal `auto` has, and it never overrides a choice."""
    assert resolve_local_protocol(base_url, configured) == expected
