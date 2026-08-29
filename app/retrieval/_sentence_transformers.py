"""Shared lazy import boundary for local sentence-transformer providers."""

from collections.abc import Callable
from importlib import import_module
from threading import Lock

_MISSING_EXTRA_MESSAGE = (
    "sentence-transformers is not installed; run one of "
    "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
)


class ThreadSafeLazy[T]:
    """Construct and cache one value safely across simultaneous worker threads."""

    def __init__(self) -> None:
        self._value: T | None = None
        self._lock = Lock()

    @property
    def value(self) -> T | None:
        """Return the cached value without constructing it."""
        return self._value

    def get(self, factory: Callable[[], T]) -> T:
        """Return the cached value, constructing it once when absent."""
        cached = self._value
        if cached is not None:
            return cached

        with self._lock:
            cached = self._value
            if cached is None:
                cached = factory()
                self._value = cached
            return cached


def sentence_transformers_attribute(name: str) -> object:
    """Return one lazily imported ``sentence_transformers`` attribute."""
    try:
        module = import_module("sentence_transformers")
    except ImportError as exc:
        raise RuntimeError(_MISSING_EXTRA_MESSAGE) from exc
    return getattr(module, name)
