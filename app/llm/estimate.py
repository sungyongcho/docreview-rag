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
from tiktoken.model import MODEL_PREFIX_TO_ENCODING, MODEL_TO_ENCODING

from app.llm.schemas import Prompt

log = logging.getLogger(__name__)

#: Fixed allowance for chat-template turn markers around the system and user halves.
FRAMING_TOKENS = 16
FALLBACK_ENCODING = "o200k_base"
_unavailable: set[str] = set()


def prompt_encoding(model_name: str) -> str:
    """Return the tokenizer name for ``model_name`` without loading any tokenizer data.

    Only the name tables are consulted, so a recognized OpenAI model in an offline
    container reaches the same guarded loader as an unknown local model.
    """
    name = MODEL_TO_ENCODING.get(model_name)
    if name is None:
        name = next(
            (
                encoding
                for prefix, encoding in MODEL_PREFIX_TO_ENCODING.items()
                if model_name.startswith(prefix)
            ),
            None,
        )
    return name or FALLBACK_ENCODING


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
    """Return whether the projection does not fit the remaining allowance.

    The comparison uses the configured allowance as-is: estimation uncertainty is not
    turned into extra budget. The fallback encoding undercounts rather than overcounts,
    so a projection that slips through still meets the post-hoc usage check.
    """
    return projected > allowance
