"""Refresh an isolated DEV frontend from the canonical web source without restarting its API."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
UI_IMAGE = "docreview-ui:dev-local"


@dataclass(frozen=True)
class RunningDev:
    """Pin the running API process while only its static frontend is replaced."""

    container_id: str
    started_at: str


def inspect_dev(container: str) -> RunningDev:
    """Reject non-running or non-DEV targets without printing environment secrets."""
    result = subprocess.run(
        ["docker", "inspect", "--type", "container", container],
        check=True,
        capture_output=True,
        text=True,
    )
    record = json.loads(result.stdout)[0]
    environment = dict(entry.split("=", 1) for entry in record["Config"]["Env"])
    mode = environment.get("MODE", environment.get("DOCREVIEW_ENVIRONMENT"))
    if mode != "dev" or environment.get("DOCREVIEW_ADMIN_MODE") != "live":
        raise ValueError("UI refresh requires a DEV container with live administrator mode.")
    if not record["State"]["Running"]:
        raise ValueError("The DEV API container must already be running.")
    return RunningDev(record["Id"], record["State"]["StartedAt"])


def refresh(container: str, *, dry_run: bool = False) -> None:
    """Build the existing web-only Docker target and copy assets into the pinned DEV API."""
    before = inspect_dev(container)
    command = [
        "docker",
        "build",
        "--target",
        "web",
        "--build-arg",
        "NEXT_PUBLIC_ADMIN_MODE=live",
        "--build-arg",
        "NEXT_PUBLIC_API_BASE_URL=",
        "--tag",
        UI_IMAGE,
        "--file",
        str(ROOT / "docker" / "Dockerfile"),
        str(ROOT),
    ]
    print(f"UI source: {ROOT / 'web'}")
    print(f"DEV target: {container}; API process and installed packages will be preserved.")
    if dry_run:
        print("Dry run: build web target, then copy only /web/out into /app/web/out.")
        return
    subprocess.run(command, check=True)
    if inspect_dev(container) != before:
        raise RuntimeError("The DEV container changed during the build; no assets were copied.")
    with tempfile.TemporaryDirectory(prefix="docreview-dev-ui-") as temporary:
        created = subprocess.run(
            ["docker", "create", UI_IMAGE],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if len(created) != 64 or any(char not in "0123456789abcdef" for char in created):
            raise RuntimeError("Docker returned an invalid temporary container identity.")
        try:
            subprocess.run(["docker", "cp", f"{created}:/web/out/.", temporary], check=True)
            if inspect_dev(container) != before:
                raise RuntimeError("The DEV container changed; no assets were copied.")
            # Keep old hashed assets available to tabs that are already open.
            subprocess.run(
                ["docker", "cp", f"{temporary}/.", f"{container}:/app/web/out/"], check=True
            )
        finally:
            subprocess.run(["docker", "rm", created], check=True, capture_output=True)
    if inspect_dev(container) != before:
        raise RuntimeError("The DEV API process changed while assets were copied.")
    print("DEV UI refreshed. Reload the browser; the API container was not restarted.")


def main() -> int:
    """Accept an explicit DEV container and an optional read-only preview."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    refresh(args.container, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
