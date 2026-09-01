"""Build the current web source in an isolated temporary checkout."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main() -> int:
    """Copy current web sources, reuse dependencies, and return the Next build exit code."""
    root = Path(__file__).resolve().parents[1]
    source = root / "web"
    dependencies = source / "node_modules"
    if not dependencies.is_dir():
        raise RuntimeError("web/node_modules is missing; run npm install in web first")
    ignored = shutil.ignore_patterns("node_modules", ".next", ".next-*", "out", "*.tsbuildinfo")
    with tempfile.TemporaryDirectory(prefix="docreview-web-build-") as temporary:
        target = Path(temporary) / "web"
        shutil.copytree(source, target, ignore=ignored)
        target_dependencies = target / "node_modules"
        try:
            shutil.copytree(
                dependencies,
                target_dependencies,
                copy_function=os.link,
                symlinks=True,
            )
        except OSError:
            shutil.rmtree(target_dependencies, ignore_errors=True)
            shutil.copytree(dependencies, target_dependencies, symlinks=True)
        environment = dict(os.environ)
        environment.pop("NEXT_DIST_DIR", None)
        completed = subprocess.run(
            ["npm", "run", "build"],
            cwd=target,
            env=environment,
            check=False,
        )
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
