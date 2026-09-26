"""Pre-flight prompt projection: encodings, framing and offline fallback."""

import tiktoken

import app.llm.estimate as estimate
from app.llm.estimate import FRAMING_TOKENS, RETRY_AFTER_S, estimate_prompt_tokens, prompt_encoding
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
    """An uncached encoding for a known OpenAI model is skipped and not retried within
    the back-off."""
    loads: list[str] = []

    def unavailable(name):
        """Fail every load attempt and record the encoding asked for."""
        loads.append(name)
        raise OSError(f"{name} is not cached")

    monkeypatch.setattr(estimate, "_encoding", unavailable)
    monkeypatch.setattr(estimate, "_failed_at", {})
    prompt = Prompt(system="s", user="u")

    assert estimate_prompt_tokens(prompt, model_name="text-embedding-3-large") is None
    assert estimate_prompt_tokens(prompt, model_name="text-embedding-3-large") is None
    assert estimate_prompt_tokens(prompt, model_name="gemma4:e4b") is None
    assert loads == ["cl100k_base", "o200k_base"]


def test_tokenizer_load_is_retried_once_the_back_off_has_elapsed(monkeypatch):
    """A transient load failure pauses the projection for the back-off interval only; the
    next call after it loads the encoding again instead of staying disabled for the process."""
    loads: list[str] = []
    cached = False

    def loader(name):
        """Fail until the encoding is 'downloaded', recording every attempt."""
        loads.append(name)
        if not cached:
            raise OSError(f"{name} is not cached")
        return tiktoken.get_encoding(name)

    monkeypatch.setattr(estimate, "_encoding", loader)
    monkeypatch.setattr(estimate, "_failed_at", {})
    prompt = Prompt(system="s", user="u")
    encoding = tiktoken.get_encoding("o200k_base")
    expected = len(encoding.encode("s")) + len(encoding.encode("u")) + FRAMING_TOKENS
    started = 1_000.0

    assert estimate_prompt_tokens(prompt, model_name="gemma4:e4b", clock=lambda: started) is None
    cached = True
    within = started + RETRY_AFTER_S - 1
    assert estimate_prompt_tokens(prompt, model_name="gemma4:e4b", clock=lambda: within) is None
    assert loads == ["o200k_base"], "no retry within the back-off"
    elapsed = started + RETRY_AFTER_S
    projected = estimate_prompt_tokens(prompt, model_name="gemma4:e4b", clock=lambda: elapsed)
    assert projected == expected
    assert loads == ["o200k_base", "o200k_base"]
    assert "o200k_base" not in estimate._failed_at, "a successful load clears the back-off"
