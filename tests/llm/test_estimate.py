"""Pre-flight prompt projection: encodings, framing and offline fallback."""

import tiktoken

import app.llm.estimate as estimate
from app.llm.estimate import (
    FRAMING_TOKENS,
    estimate_prompt_tokens,
    prompt_encoding,
)
from app.llm.schemas import Prompt


def test_projection_counts_both_halves_and_chat_framing():
    """The projection is the encoded system plus user text plus the fixed framing allowance."""
    prompt = Prompt(system="Return one strict evidence decision.", user="What changed in FY2024?")
    encoding = tiktoken.get_encoding("o200k_base")
    expected = len(encoding.encode(prompt.system)) + len(encoding.encode(prompt.user))

    assert estimate_prompt_tokens(prompt, model_name="gemma4:e4b") == expected + FRAMING_TOKENS


def test_encoding_names_resolve_from_model_tables_without_loading_tokenizer_data(monkeypatch):
    """OpenAI names resolve through the model tables, local names use the o200k fallback,
    and neither resolution loads tokenizer data."""

    def forbidden(*args, **kwargs):
        """Fail any attempt to load tokenizer data while a name is resolved."""
        raise AssertionError("tokenizer data must not be loaded to resolve a name")

    monkeypatch.setattr(tiktoken, "get_encoding", forbidden)
    monkeypatch.setattr(tiktoken, "encoding_for_model", forbidden)

    assert prompt_encoding("gemma4:e4b") == "o200k_base"
    assert prompt_encoding("text-embedding-3-large") == "cl100k_base"
    assert prompt_encoding("gpt-4o-mini") == "o200k_base"
    assert prompt_encoding("gpt-4-0613") == "cl100k_base"


def test_recognized_models_reach_the_same_guarded_loader_as_unknown_ones(monkeypatch):
    """An uncached encoding for a known OpenAI model is skipped once and never retried."""
    loads: list[str] = []

    def unavailable(name):
        """Fail every load attempt and record the encoding asked for."""
        loads.append(name)
        raise OSError(f"{name} is not cached")

    monkeypatch.setattr(estimate, "_encoding", unavailable)
    monkeypatch.setattr(estimate, "_unavailable", set())
    prompt = Prompt(system="s", user="u")

    assert estimate_prompt_tokens(prompt, model_name="text-embedding-3-large") is None
    assert estimate_prompt_tokens(prompt, model_name="text-embedding-3-large") is None
    assert estimate_prompt_tokens(prompt, model_name="gemma4:e4b") is None
    assert loads == ["cl100k_base", "o200k_base"]
