"""Plain terminal steps and explicit choices shared by local setup commands."""

import sys

from scripts.stack.terminal import colors


class SetupCancelledError(RuntimeError):
    """The user stopped setup before the next action was submitted."""


def step(number: int, total: int, title: str, intent: str) -> None:
    """Explain the next action in a single compact terminal-aware line."""
    label = f"[{number}/{total}] {title}"
    if colors():
        label = f"\033[36;1m{label}\033[0m"
    print(f"\n{label}: {intent}", flush=True)


def confirm(message: str) -> bool:
    """Require an interactive affirmative answer; EOF and noninteractive input decline."""
    if not sys.stdin.isatty():
        return False
    try:
        return input(message + " (Y/n) ") == "Y"
    except EOFError:
        return False
