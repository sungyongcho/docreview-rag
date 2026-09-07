"""Preview and reset one checkout while preserving explicit local configuration."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import subprocess
import sys
import time
from urllib.parse import urlparse

from scripts.stack.operator import LocalOperator
from scripts.stack.prompts import confirm
from scripts.stack.terminal import activity, run_step

PRESERVED = {".git", ".agents", ".claude", ".codex", ".vscode", ".idea", ".freshstart-keep"}
VOLUMES = {"pg_data", "web_next", "web_node_modules", "ollama_models"}


def git(root: Path, *args: str) -> str:
    """Read this worktree's Git state without executing shell substitutions."""
    return subprocess.check_output(["git", "-C", str(root), *args], text=True)


def receipt_path(root: Path, command: str) -> Path:
    """Store receipts outside the deletion set in the current worktree's Git directory."""
    path = Path(git(root, "rev-parse", "--git-path", f"docreview-receipts/{command}.json").strip())
    return path if path.is_absolute() else root / path


def write_receipt(root: Path, command: str, **values: object) -> None:
    """Atomically retain completed steps without storing configuration or credentials."""
    path = receipt_path(root, command)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"command": command, "updated": time.time(), **values}, indent=2)
    )
    temporary.replace(path)


def status(root: Path, command: str) -> int:
    """Read this command's receipt without requiring services or a surviving environment."""
    path = receipt_path(root, command)
    if not path.exists():
        print(f"No {command} receipt exists for this checkout.")
        return 0
    result = json.loads(path.read_text())
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "succeeded" else 1


def inventory(root: Path, *, extreme: bool, discard_tracked: bool) -> dict:
    """Pin removable file identities and tracked changes; never follow directory links."""
    root = root.resolve()
    if Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
        raise ValueError("Run from a Git checkout root; nothing changed.")
    keep = set(PRESERVED)
    keep_file = root / ".freshstart-keep"
    if keep_file.is_symlink():
        raise ValueError(".freshstart-keep must not be a symlink; nothing changed.")
    if keep_file.exists():
        for line in keep_file.read_text().splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or value in {".", ""}:
                raise ValueError(".freshstart-keep entries must be checkout-relative paths.")
            keep.add(path.as_posix().rstrip("/"))
    tracked = set(filter(None, git(root, "ls-files", "-z").split("\0")))
    changed = set(filter(None, git(root, "diff", "--name-only", "-z").split("\0")))
    changed.update(filter(None, git(root, "diff", "--cached", "--name-only", "-z").split("\0")))
    outside = sorted(path for path in changed if not path.startswith("data/"))
    if outside and not discard_tracked:
        raise ValueError(
            "Tracked changes outside data/ block cleanup: "
            + ", ".join(outside)
            + ". Review them or explicitly use --discard-tracked; nothing changed."
        )
    if git(root, "ls-files", "-u", "-z"):
        raise ValueError("Resolve unmerged Git entries first; nothing changed.")

    def preserved(relative: str) -> bool:
        """Protect exact paths and descendants, including root environment files."""
        return any(relative == item or relative.startswith(item + "/") for item in keep) or (
            not extreme and relative.split("/", 1)[0].startswith(".env")
        )

    files = {}
    directories = []

    def visit(directory: Path) -> None:
        """Inspect real directory entries while refusing unsafe source trees."""
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root).as_posix()
            if preserved(relative):
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) and (relative == "data" or relative.startswith("data/")):
                raise ValueError(f"Symlink under data/ refused: {relative}; nothing changed.")
            if path.name == ".git":
                raise ValueError(f"Nested Git repository refused: {relative}; nothing changed.")
            if stat.S_ISDIR(info.st_mode):
                visit(path)
                if not any(item.startswith(relative + "/") for item in tracked | keep):
                    directories.append(relative)
            elif relative not in tracked:
                files[relative] = [
                    info.st_dev,
                    info.st_ino,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_mode,
                ]

    visit(root)
    revert = sorted(path for path in changed if not preserved(path))
    # Environment templates are tracked product files, even in extreme mode.
    return {
        "files": files,
        "directories": directories,
        "revert": revert,
        "head": git(root, "rev-parse", "HEAD").strip(),
        "worktree_diff": hashlib.sha256(git(root, "diff", "--binary").encode()).hexdigest(),
        "index_diff": hashlib.sha256(
            git(root, "diff", "--cached", "--binary").encode()
        ).hexdigest(),
    }


def docker_inventory(root: Path, *, extreme: bool) -> dict:
    """Pin local daemon resources using project, checkout and resource ownership labels."""
    host = os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else None
    if not host:
        context = json.loads(subprocess.check_output(["docker", "context", "inspect"], text=True))
        host = context[0]["Endpoints"]["docker"]["Host"]
    endpoint = urlparse(host)
    if (
        endpoint.scheme != "unix"
        or endpoint.netloc
        or endpoint.query
        or endpoint.fragment
        or not stat.S_ISSOCK(Path(endpoint.path).stat().st_mode)
    ):
        raise ValueError("Fresh start requires a local Docker Unix socket.")
    docker = ["docker", "--host", host]
    project = root.name

    def output(*arguments: str) -> str:
        """Capture only read-only Docker inventory calls against the pinned daemon."""
        return subprocess.check_output([*docker, *arguments], text=True).strip()

    ids = output(
        "ps", "-aq", "--no-trunc", "--filter", f"label=com.docker.compose.project={project}"
    ).split()
    containers = []
    images = set()
    for identifier in ids:
        row = json.loads(output("inspect", identifier))[0]
        labels = row["Config"].get("Labels") or {}
        if (
            labels.get("com.docker.compose.project") != project
            or Path(labels.get("com.docker.compose.project.working_dir", "")).resolve()
            != root.resolve()
        ):
            raise ValueError("A Compose project name belongs to another checkout; nothing changed.")
        containers.append(row["Id"])
    names = output(
        "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"
    ).split()
    volumes = []
    for name in names:
        row = json.loads(output("volume", "inspect", name))[0]
        labels = row.get("Labels") or {}
        kind = labels.get("com.docker.compose.volume")
        if kind not in VOLUMES or kind == "ollama_models" and not extreme:
            continue
        if (
            labels.get("com.docker.compose.project") != project
            or row.get("Driver") != "local"
            or row.get("Options")
        ):
            raise ValueError("Volume ownership is not local to this project; nothing changed.")
        users = output("ps", "-aq", "--no-trunc", "--filter", f"volume={name}").split()
        if not set(users).issubset(containers):
            raise ValueError("A target volume is shared outside this checkout; nothing changed.")
        volumes.append(name)
    image_ids = output(
        "image", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"
    ).split()
    for identifier in sorted(set(image_ids)):
        row = json.loads(output("image", "inspect", identifier))[0]
        labels = row["Config"].get("Labels") or {}
        service = labels.get("com.docker.compose.service")
        tags = row.get("RepoTags") or []
        if labels.get("com.docker.compose.project") != project or not service:
            continue
        if any(tag != f"{project}-{service}:latest" for tag in tags):
            continue  # Match Compose --rmi local: preserve explicitly tagged images.
        users = output("ps", "-aq", "--no-trunc", "--filter", f"ancestor={row['Id']}").split()
        if not set(users).issubset(containers):
            raise ValueError("A built image is shared outside this checkout; nothing changed.")
        images.add(row["Id"])
    return {
        "docker": docker,
        "containers": sorted(containers),
        "volumes": sorted(volumes),
        "images": sorted(images),
    }


def preview(root: Path, files: dict, resources: dict) -> None:
    """Show numbered top-level file totals and the exact tracked/Docker deletion scope."""
    print(f"Fresh-start preview: {root}\nNo backup will be created.")
    groups = defaultdict(lambda: [0, 0])
    for name, info in files["files"].items():
        group = groups[name.split("/", 1)[0]]
        group[0] += 1
        group[1] += info[2]
    rows = [
        f"{name}: {count} files, {size:,} bytes" for name, (count, size) in sorted(groups.items())
    ]
    rows.extend("Revert tracked: " + path for path in files["revert"])
    for kind in ("containers", "volumes", "images"):
        rows.extend(f"{kind}: {item}" for item in resources[kind])
    for number, row in enumerate(rows, 1):
        print(f"  {number}. {row}")


@contextmanager
def parent_descriptor(root: Path, relative: str) -> Iterator[tuple[int, str]]:
    """Anchor each parent at the checkout descriptor and refuse symlink traversal."""
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or ".." in parts:
        raise ValueError("Invalid checkout deletion path.")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor, parts[-1]
    finally:
        os.close(descriptor)


def remove_file(root: Path, relative: str, expected: list[int]) -> None:
    """Unlink a previewed inode relative to an anchored parent, never a replacement path."""
    with parent_descriptor(root, relative) as (descriptor, name):
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode] != expected:
            raise ValueError(f"Removal target changed: {relative}. Cleanup stopped.")
        os.unlink(name, dir_fd=descriptor)


def remove_directory(root: Path, relative: str) -> None:
    """Remove only empty real directories through the same anchored traversal guard."""
    with parent_descriptor(root, relative) as (descriptor, name):
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
        try:
            if not os.listdir(child):
                os.rmdir(name, dir_fd=descriptor)
        finally:
            os.close(child)


def remove_files(root: Path, files: dict) -> None:
    """Attempt removals first, report actual permission failures once, then retry once."""
    failed_files = []
    failed_directories = []
    for relative, expected in files["files"].items():
        try:
            remove_file(root, relative, expected)
        except PermissionError:
            failed_files.append(relative)
    for relative in files["directories"]:
        try:
            remove_directory(root, relative)
        except PermissionError:
            failed_directories.append(relative)
    failures = failed_files + failed_directories
    if not failures:
        return
    repair = sorted({(root / relative).parent for relative in failures})
    print("Removal failed for:")
    for relative in failures:
        print("  " + str(root / relative))
    print(
        'Run as the host user: sudo chown -R "$(id -u):$(id -g)" -- '
        + " ".join(shlex.quote(str(path)) for path in repair)
    )
    if not confirm("After applying that repair, retry the failed removals once?"):
        raise RuntimeError("Cleanup is partial; failed removals were not retried.")
    for relative in failed_files:
        remove_file(root, relative, files["files"][relative])
    # Successfully removed directories are gone; failed parents may now be empty.
    for relative in files["directories"]:
        if (root / relative).exists():
            remove_directory(root, relative)


def start_fresh(
    root: Path, *, extreme: bool = False, no_start: bool = False, discard_tracked: bool = False
) -> int:
    """Delete only a confirmed, unchanged checkout inventory and optionally bootstrap again."""
    if not sys.stdin.isatty():
        raise ValueError("Run interactively to review the preview; nothing changed.")
    root = root.resolve()
    files = inventory(root, extreme=extreme, discard_tracked=discard_tracked)
    resources = docker_inventory(root, extreme=extreme)
    preview(root, files, resources)
    expires = time.monotonic() + 300
    if not confirm("Remove this previewed checkout data and Docker resources?") or (
        extreme and not confirm("Also delete previewed .env* files and Ollama models?")
    ):
        print("Cancelled; nothing changed.")
        return 0
    if time.monotonic() >= expires:
        raise ValueError("Preview expired; nothing changed.")
    if files != inventory(
        root, extreme=extreme, discard_tracked=discard_tracked
    ) or resources != docker_inventory(root, extreme=extreme):
        raise ValueError("Preview changed; nothing changed. Run again for a new preview.")
    completed = []
    write_receipt(root, "start-fresh", status="running", completed=completed)
    try:
        LocalOperator(root).stop()
        # Explicit IDs match down -v --rmi local deletion scope, excluding new resources.
        for kind, arguments in (
            ("containers", ["rm", "-f"]),
            ("volumes", ["volume", "rm"]),
            ("images", ["image", "rm"]),
        ):
            if resources[kind]:
                run_step(
                    "Remove project " + kind,
                    [*resources["docker"], *arguments, *resources[kind]],
                    cwd=root,
                )
            completed.append(kind)
            write_receipt(root, "start-fresh", status="running", completed=completed)
        with activity("Remove checkout files"):
            remove_files(root, files)
        completed.append("files")
        if files["revert"]:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "restore",
                    "--source=HEAD",
                    "--staged",
                    "--worktree",
                    "--",
                    *files["revert"],
                ],
                check=True,
            )
        completed.append("tracked files")
        write_receipt(root, "start-fresh", status="succeeded", completed=completed, restarted=False)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        KeyboardInterrupt,
    ) as error:
        write_receipt(
            root, "start-fresh", status="failed", completed=completed, error=type(error).__name__
        )
        raise
    print(
        "Checkout cleanup complete. Browser localStorage is unchanged; clear it in "
        "Settings > Data and help (설정 › 데이터와 도움말)."
    )
    if extreme:
        print(
            "Services remain stopped. Run rag-start-quick to create .env and prepare setup again."
        )
    elif not no_start:
        result = subprocess.run(
            ["bash", str(root / "scripts/stack/quickstart.sh")], cwd=root, check=False
        )
        write_receipt(
            root,
            "start-fresh",
            status="succeeded" if result.returncode == 0 else "failed",
            completed=completed,
            restarted=result.returncode == 0,
        )
        return result.returncode
    return 0


def main() -> int:
    """Expose cleanup before a virtual environment exists, using only the standard library."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extreme", action="store_true")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--discard-tracked", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--verbose", "-vv", action="store_true")
    args = parser.parse_args()
    if args.verbose:
        os.environ["DOCREVIEW_VERBOSE"] = "1"
    root = Path(__file__).resolve().parents[2]
    try:
        return (
            status(root, "start-fresh")
            if args.status
            else start_fresh(
                root,
                extreme=args.extreme,
                no_start=args.no_start,
                discard_tracked=args.discard_tracked,
            )
        )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt, EOFError:
        print(
            "Interrupted. Run rag-start-fresh --status before requesting another preview.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
