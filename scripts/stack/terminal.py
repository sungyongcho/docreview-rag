"""Small dependency-free progress lines with bounded failure output."""

from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time


def colors() -> bool:
    """Use terminal decoration only when output supports it and the user has not opted out."""
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


@contextmanager
def activity(title: str) -> Iterator[None]:
    """Show elapsed state for in-process work without capturing interactive prompts."""
    started = time.monotonic()
    print(("\033[36m◐\033[0m" if colors() else "[....]") + " " + title, flush=True)
    try:
        yield
    except Exception, KeyboardInterrupt:
        print(f"[FAIL] {title} {time.monotonic() - started:.0f}s", flush=True)
        raise
    else:
        state = "\033[32m✔\033[0m" if colors() else "[ OK ]"
        print(f"{state} {title} {time.monotonic() - started:.0f}s", flush=True)


def run_step(
    title: str, command: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Run a command once, stream verbose logs or retain a bounded tail on failure."""
    verbose = (env or os.environ).get("DOCREVIEW_VERBOSE") == "1"
    started = time.monotonic()
    decorated = colors()
    done = threading.Event()

    def spin() -> None:
        """Refresh one terminal line until the command completes."""
        index = 0
        while not done.wait(0.12):
            print(f"\r\033[36m{'◐◓◑◒'[index % 4]}\033[0m {title}…", end="", flush=True)
            index += 1

    spinner = threading.Thread(target=spin, daemon=True) if decorated and not verbose else None
    if spinner:
        spinner.start()
    else:
        print(f"[....] {title}", flush=True)
    tail = deque(maxlen=20)
    try:
        with subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                tail.append(line.rstrip())
                if verbose:
                    print(line, end="", flush=True)
            code = process.wait()
    except OSError:
        print(f"[FAIL] {title}", file=sys.stderr)
        print("Rerun: " + shlex.join(["env", "DOCREVIEW_VERBOSE=1", *command]), file=sys.stderr)
        raise
    finally:
        done.set()
        if spinner:
            spinner.join()
            print("\r\033[2K", end="", flush=True)
    elapsed = time.monotonic() - started
    state = (
        ("\033[32m✔\033[0m" if code == 0 else "\033[31m✘\033[0m")
        if decorated
        else ("[ OK ]" if code == 0 else "[FAIL]")
    )
    print(f"{state} {title} {elapsed:.0f}s", flush=True)
    if code:
        if not verbose:
            print("\n".join(tail), file=sys.stderr)
        print("Rerun: " + shlex.join(["env", "DOCREVIEW_VERBOSE=1", *command]), file=sys.stderr)
        raise subprocess.CalledProcessError(code, command)
    return subprocess.CompletedProcess(command, code)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("title")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        run_step(
            args.title,
            args.command[1:] if args.command[:1] == ["--"] else args.command,
            cwd=Path.cwd(),
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
