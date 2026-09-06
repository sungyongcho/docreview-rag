"""Exact token and character budgets for complete retrieval embedding inputs."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

TARGET_INPUT_TOKENS = 2_048
MAX_INPUT_TOKENS = 8_192
MAX_REQUEST_TOKENS = 300_000
MAX_REQUEST_INPUTS = 2_048
MAX_INPUT_CHARACTERS = 12_000


@lru_cache(maxsize=4)
def tokenizer(model: str) -> tiktoken.Encoding:
    """Resolve the actual model tokenizer without guessing an unknown encoding."""
    return tiktoken.encoding_for_model(model)


def count_tokens(text: str, model: str = "text-embedding-3-large") -> int:
    """Count source text literally, including strings resembling special tokens."""
    return len(tokenizer(model).encode(text, disallowed_special=()))


@dataclass(frozen=True, slots=True)
class InputBudget:
    """Bound the complete context and source body used for indexing."""

    model: str = "text-embedding-3-large"
    target_tokens: int = TARGET_INPUT_TOKENS
    max_tokens: int = MAX_INPUT_TOKENS
    max_chars: int = MAX_INPUT_CHARACTERS
    token_counter: Callable[[str], int] | None = None

    def __post_init__(self) -> None:
        """Reject inconsistent or unsupported embedding input budgets."""
        if not 0 < self.target_tokens <= self.max_tokens <= MAX_INPUT_TOKENS:
            raise ValueError("token budgets require 0 < target <= maximum <= 8192")
        if self.max_chars <= 0:
            raise ValueError("character budget must be positive")

    def accepts(self, text: str, *, target: bool = False) -> bool:
        """Check both complete-input size bounds without truncating evidence."""
        if not text or len(text) > self.max_chars:
            return False
        limit = self.target_tokens if target else self.max_tokens
        tokens = (
            self.token_counter(text)
            if self.token_counter is not None
            else count_tokens(text, self.model)
        )
        if not isinstance(tokens, int) or tokens < 0:
            raise ValueError("token counter must return a nonnegative integer")
        return tokens <= limit


def validate_request(texts: Sequence[str], *, model: str) -> tuple[int, ...]:
    """Reject oversized inputs or aggregate requests before a provider call."""
    if len(texts) > MAX_REQUEST_INPUTS:
        raise ValueError(f"embedding request exceeds {MAX_REQUEST_INPUTS} inputs")
    counts: list[int] = []
    total = 0
    for position, text in enumerate(texts):
        if not isinstance(text, str) or not text:
            raise ValueError(f"embedding input {position} must be a nonempty string")
        count = count_tokens(text, model)
        if count > MAX_INPUT_TOKENS:
            raise ValueError(
                f"embedding input {position} exceeds {MAX_INPUT_TOKENS} tokens: {count}"
            )
        total += count
        if total > MAX_REQUEST_TOKENS:
            raise ValueError(f"embedding request exceeds {MAX_REQUEST_TOKENS} aggregate tokens")
        counts.append(count)
    return tuple(counts)
