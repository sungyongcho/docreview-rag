"""Relay stdio between a client and a real server module, recording each direction.

Run as ``python -m tests.mcp.stdio_relay <directory> <server module> [server args...]``;
any further arguments are passed to the server module unchanged. Bytes pass through
unchanged, so the SDK still owns every protocol decision.
"""

from pathlib import Path
import subprocess
import sys
import threading


def relay(directory: Path, module: str, *server_args: str) -> int:
    """Forward lines unchanged and append each direction to its own JSONL file."""
    with subprocess.Popen(
        [sys.executable, "-m", module, *server_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as server:
        assert server.stdin is not None and server.stdout is not None
        server_stdin, server_stdout = server.stdin, server.stdout

        def forward_requests() -> None:
            """Copy client lines to the server until the client closes stdin."""
            with (directory / "requests.jsonl").open("wb") as recording:
                for line in sys.stdin.buffer:
                    recording.write(line)
                    recording.flush()
                    server_stdin.write(line)
                    server_stdin.flush()
            server_stdin.close()

        threading.Thread(target=forward_requests, daemon=True).start()
        with (directory / "responses.jsonl").open("wb") as recording:
            for line in server_stdout:
                recording.write(line)
                recording.flush()
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
        return server.wait()


if __name__ == "__main__":
    raise SystemExit(relay(Path(sys.argv[1]), sys.argv[2], *sys.argv[3:]))
