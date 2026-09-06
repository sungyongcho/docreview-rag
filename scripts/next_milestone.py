"""Run the focused commands for the milestone named by learning.toml."""

from pathlib import Path
import shlex
import subprocess
import sys
import tomllib

PROJECT = Path(__file__).resolve().parents[1] / "docs" / "project"


def milestone_commands(milestone: str) -> list[str]:
    """Return the focused commands registered for one checkpoint id."""
    config = tomllib.loads((PROJECT / "tutorial-code.toml").read_text(encoding="utf-8"))
    commands = [
        command
        for module in config.get("modules", [])
        for group in module.get("groups", [])
        if group.get("id") == milestone
        for command in group.get("commands", [])
    ]
    if not commands:
        raise SystemExit(f"no focused commands registered for {milestone}")
    return commands


def main() -> int:
    """Run every focused command for the next milestone, stopping on failure."""
    learning = tomllib.loads((PROJECT / "learning.toml").read_text(encoding="utf-8"))
    milestone = learning["learning"]["next_milestone"]
    print(f"next milestone: {milestone}")
    for command in milestone_commands(milestone):
        print(f"$ {command}")
        result = subprocess.run(shlex.split(command), check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
