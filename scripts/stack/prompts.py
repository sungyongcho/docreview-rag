"""Plain terminal steps and explicit choices shared by local setup commands."""

import sys


class SetupCancelledError(RuntimeError):
    """The user stopped setup before the next action was submitted."""


def step(number: int, total: int, title: str, intent: str) -> None:
    """Explain an action before running it using an ASCII-only, color-free header."""
    print(f"\n+-- [{number}/{total}] {title} --+", flush=True)
    print(intent, flush=True)


def confirm(message: str) -> bool:
    """Require an interactive affirmative answer; EOF and noninteractive input decline."""
    if not sys.stdin.isatty():
        return False
    try:
        return input(message + " [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False
