"""Pre-flight prompt projection: encodings, framing, the allowance boundary and offline fallback."""

import tiktoken

import app.llm.estimate as estimate
from app.llm.estimate import (
    FRAMING_TOKENS,
    estimate_prompt_tokens,
    exceeds_allowance,
    prompt_encoding,
)
from app.llm.schemas import Prompt


def test_projection_counts_both_halves_and_chat_framing():
    """The projection is the encoded system plus user text plus the fixed framing allowance."""
    prompt = Prompt(system="Return one strict evidence decision.", user="What changed in FY2024?")
    encoding = tiktoken.get_encoding("o200k_base")
    expected = len(encoding.encode(prompt.system)) + len(encoding.encode(prompt.user))

    assert estimate_prompt_tokens(prompt, model_name="gemma4:e4b") == expected + FRAMING_TOKENS


def test_unknown_models_fall_back_to_o200k_and_openai_models_use_their_encoding():
    """Local model names have no tiktoken entry and use the fallback; OpenAI names do not."""
    assert prompt_encoding("gemma4:e4b") == "o200k_base"
    assert prompt_encoding("text-embedding-3-large") == "cl100k_base"
    assert prompt_encoding("gpt-4o-mini") == "o200k_base"
    assert prompt_encoding("gpt-4-0613") == "cl100k_base"


def test_encoding_names_resolve_without_loading_tokenizer_data(monkeypatch):
    """Resolving a name touches only the model tables, never a tokenizer download."""

    def forbidden(*args, **kwargs):
        """Fail any attempt to load tokenizer data while a name is resolved."""
        raise AssertionError("tokenizer data must not be loaded to resolve a name")

    monkeypatch.setattr(tiktoken, "get_encoding", forbidden)
    monkeypatch.setattr(tiktoken, "encoding_for_model", forbidden)

    assert prompt_encoding("gpt-4o-mini") == "o200k_base"
    assert prompt_encoding("text-embedding-3-large") == "cl100k_base"
    assert prompt_encoding("gemma4:e4b") == "o200k_base"


def test_projection_is_skipped_and_not_retried_when_no_encoding_loads(monkeypatch):
    """A tokenizer that cannot load disables projection for that encoding without retries."""
    loads = {"count": 0}

    def unavailable(name):
        """Fail every load attempt and count them."""
        loads["count"] += 1
        raise OSError(f"{name} is not cached")

    monkeypatch.setattr(estimate, "_encoding", unavailable)
    monkeypatch.setattr(estimate, "_unavailable", set())
    prompt = Prompt(system="s", user="u")

    assert estimate_prompt_tokens(prompt, model_name="gemma4:e4b") is None
    assert estimate_prompt_tokens(prompt, model_name="gemma4:e4b") is None
    assert loads["count"] == 1


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


def test_projection_is_refused_only_when_it_exceeds_the_allowance():
    """A projection equal to the allowance is sent; one token more is refused."""
    assert exceeds_allowance(1_000, 1_000) is False
    assert exceeds_allowance(1_001, 1_000) is True
    assert exceeds_allowance(0, 0) is False
    assert exceeds_allowance(1, 0) is True
