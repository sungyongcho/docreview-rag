"""Pre-flight prompt size projection shared by the provider boundary.

The projection decides whether a request can fit the remaining input allowance before any
token is paid for. It is an estimate and stays separate from reported usage: OpenAI models
count with their own ``tiktoken`` encoding, and every other model falls back to
``o200k_base``, which undercounts English slightly and stays far closer to sentence-piece
vocabularies on Korean filing text than ``cl100k_base`` does.
"""

from __future__ import annotations

from functools import lru_cache
import logging

import tiktoken

from app.llm.schemas import Prompt

log = logging.getLogger(__name__)

#: Fraction by which a projection may exceed the allowance before the call is refused.
#: Refusing a request that would have fitted costs a whole run, while a small undercount
#: only falls through to the post-hoc accounting that exists today.
PROJECTION_TOLERANCE = 0.10
#: Fixed allowance for chat-template turn markers around the system and user halves.
FRAMING_TOKENS = 16
FALLBACK_ENCODING = "o200k_base"
_unavailable: set[str] = set()


def prompt_encoding(model_name: str) -> str:
    """Return the tokenizer name for ``model_name``: its OpenAI encoding, else the fallback."""
    try:
        return tiktoken.encoding_for_model(model_name).name
    except KeyError:
        return FALLBACK_ENCODING


@lru_cache(maxsize=4)
def _encoding(name: str) -> tiktoken.Encoding:
    """Load one encoding once per process."""
    return tiktoken.get_encoding(name)


def estimate_prompt_tokens(prompt: Prompt, *, model_name: str) -> int | None:
    """Project the input tokens of ``prompt`` for ``model_name``.

    Returns ``None`` when no tokenizer can be loaded, for example in an offline container
    that has never cached the encoding; the failure is remembered so a call never blocks
    on a repeated download attempt.
    """
    name = prompt_encoding(model_name)
    if name in _unavailable:
        return None
    try:
        encoding = _encoding(name)
    except Exception as error:  # noqa: BLE001 - a missing tokenizer must not fail the call
        _unavailable.add(name)
        log.warning("prompt projection disabled: encoding %s unavailable (%s)", name, error)
        return None
    system = len(encoding.encode(prompt.system, disallowed_special=()))
    user = len(encoding.encode(prompt.user, disallowed_special=()))
    return system + user + FRAMING_TOKENS


def exceeds_allowance(projected: int, allowance: int) -> bool:
    """Return whether the projection exceeds the allowance by more than the tolerance."""
    return projected > allowance * (1 + PROJECTION_TOLERANCE)
