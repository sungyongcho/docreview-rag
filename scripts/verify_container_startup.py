"""Verify a release image's default command under non-root, read-only, mount-free execution."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4


def inspect(kind: str, identity: str) -> dict:
    """Read Docker metadata without displaying its environment or credentials."""
    return json.loads(subprocess.check_output(["docker", kind, "inspect", identity], text=True))[0]


def verify(image: str, port: int, *, timeout: float = 90) -> None:
    """Start the immutable image without command overrides and require both health probes."""
    metadata = inspect("image", image)
    config = metadata["Config"]
    if not config.get("User") or config["User"].split(":")[0] in {"0", "root"}:
        raise RuntimeError("Image must declare a non-root default user.")
    if config.get("Volumes"):
        raise RuntimeError("Image declares volumes; mount-free verification is impossible.")
    for entry in config.get("Env", []):
        key, _, value = entry.partition("=")
        if value and any(
            part in key.upper() for part in ("API_KEY", "TOKEN", "PASSWORD", "SECRET")
        ):
            raise RuntimeError("Image contains a configured credential; use a secret-free build.")
    name = "docreview-startup-" + uuid4().hex[:12]
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--publish",
        f"127.0.0.1::{port}",
        metadata["Id"],
    ]
    print(
        json.dumps(
            {
                "image": metadata["Id"],
                "user": config["User"],
                "command": config.get("Cmd"),
                "entrypoint": config.get("Entrypoint"),
                "run": command,
            }
        ),
        flush=True,
    )
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    try:
        container = inspect("container", name)
        if (
            container["Mounts"]
            or not container["HostConfig"]["ReadonlyRootfs"]
            or container["Config"].get("Cmd") != config.get("Cmd")
            or container["Config"].get("Entrypoint") != config.get("Entrypoint")
        ):
            raise RuntimeError("Container does not satisfy the default-command isolation contract.")
        if not container["State"]["Running"]:
            raise RuntimeError(
                f"Default command exited with code {container['State']['ExitCode']}."
            )
        bindings = container["NetworkSettings"]["Ports"][f"{port}/tcp"]
        origin = "http://127.0.0.1:" + bindings[0]["HostPort"]
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = inspect("container", name)["State"]
            if not state["Running"]:
                raise RuntimeError(f"Default command exited with code {state['ExitCode']}.")
            try:
                with opener.open(origin + "/health", timeout=3) as response:
                    health = json.load(response)
                if (
                    health == {"status": "ok", "mode": "canned"}
                    and state.get("Health", {}).get("Status") == "healthy"
                ):
                    uid = subprocess.check_output(
                        ["docker", "exec", name, "id", "-u"], text=True
                    ).strip()
                    if uid == "0":
                        raise RuntimeError("Container actually runs as root.")
                    print(
                        json.dumps(
                            {
                                "health": health,
                                "docker_health": "healthy",
                                "uid": uid,
                                "mounts": [],
                                "read_only": True,
                            }
                        ),
                        flush=True,
                    )
                    return
            except URLError, TimeoutError, ConnectionError:
                pass
            time.sleep(1)
        raise RuntimeError("Default-command health readiness timed out.")
    finally:
        subprocess.run(["docker", "logs", "--tail", "40", name], check=True)
        subprocess.run(["docker", "stop", name], check=True, stdout=subprocess.DEVNULL)
        print(f"Verification container retained stopped: {name}", flush=True)


def main() -> int:
    """Accept an explicitly built release image and its published health port."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("port", type=int, choices=(8000, 7860))
    args = parser.parse_args()
    try:
        verify(args.image, args.port)
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
