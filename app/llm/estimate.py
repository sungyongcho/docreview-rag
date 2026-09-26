"""Pre-flight prompt size projection shared by the provider boundary.

The projection decides whether a request can fit the remaining input allowance before any
token is paid for. It is an estimate and stays separate from reported usage: OpenAI models
count with their own ``tiktoken`` encoding, and every other model falls back to
``o200k_base``, which undercounts English slightly and stays far closer to sentence-piece
vocabularies on Korean filing text than ``cl100k_base`` does.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
import logging
import time

import tiktoken
from tiktoken.model import MODEL_PREFIX_TO_ENCODING, MODEL_TO_ENCODING

from app.llm.schemas import Prompt

log = logging.getLogger(__name__)

#: Fixed allowance for chat-template turn markers around the system and user halves.
FRAMING_TOKENS = 16
FALLBACK_ENCODING = "o200k_base"
#: Seconds before a failed encoding load is tried again. One transient download failure
#: must not disable the projection for the rest of the process.
RETRY_AFTER_S = 60.0
#: Monotonic time of the last failed load per encoding name, cleared by a successful load.
_failed_at: dict[str, float] = {}


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


def estimate_prompt_tokens(
    prompt: Prompt, *, model_name: str, clock: Callable[[], float] = time.monotonic
) -> int | None:
    """Project the input tokens of ``prompt`` for ``model_name``.

    Parameters
    ----------
    prompt : Prompt
        System and user text to project.
    model_name : str
        Model whose encoding counts the tokens.
    clock : Callable[[], float]
        Monotonic seconds that time the back-off; injected by tests.

    Returns
    -------
    int | None
        Projected input tokens, or ``None`` when no tokenizer can be loaded, for example
        in an offline container that has never cached the encoding. The failure is
        remembered for ``RETRY_AFTER_S`` seconds so a call never blocks on an immediate
        repeat of the download attempt, and the load is tried again once that has elapsed.
    """
    name = prompt_encoding(model_name)
    now = clock()
    failed_at = _failed_at.get(name)
    if failed_at is not None and now - failed_at < RETRY_AFTER_S:
        return None
    try:
        encoding = _encoding(name)
    except Exception as error:  # noqa: BLE001 - a missing tokenizer must not fail the call
        _failed_at[name] = now
        log.warning(
            "prompt projection paused for %.0f s: encoding %s unavailable (%s)",
            RETRY_AFTER_S,
            name,
            error,
        )
        return None
    _failed_at.pop(name, None)
    system = len(encoding.encode(prompt.system, disallowed_special=()))
    user = len(encoding.encode(prompt.user, disallowed_special=()))
    return system + user + FRAMING_TOKENS
