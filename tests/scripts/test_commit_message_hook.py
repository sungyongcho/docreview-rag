"""The commit-msg hook accepts only the message form the project instructions fix.

Nothing else checks a commit message, so a commit without its Summary, Changes and
Verification is noticed only by someone reading the log afterwards.
"""

from pathlib import Path
import subprocess

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".githooks" / "commit-msg"
_BODY = "\n\nSummary\n\nWhy.\n\nChanges\n\n- What.\n\nVerification\n\n- passed: the check.\n"
_BODY_WITH_COLONS = "\n\nSummary:\nWhy.\n\nChanges:\n- What.\n\nVerification:\n- passed.\n"
_SCISSORS = "# ------------------------ >8 ------------------------\n"


def _refusal(tmp_path: Path, message: str) -> str | None:
    """Run the hook on one message; return what it says when it refuses."""
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(message, encoding="utf-8")
    done = subprocess.run(["bash", str(HOOK), str(path)], capture_output=True, text=True)
    return done.stderr if done.returncode else None


@pytest.mark.parametrize(
    "message",
    [
        "fix(agent): end the run once" + _BODY,
        "test: name the files by behaviour" + _BODY,
        "feat(api)!: drop the old route" + _BODY + "\nRefs #12\n",
        "fix(agent): end the run once" + _BODY_WITH_COLONS,
        "build(hooks): refuse a line that says Generated with a tool" + _BODY,
        "fix(agent): end the run once"
        + _BODY.replace("Why.", "Verification previously missed this case."),
        ("fix(agent): end the run once" + _BODY_WITH_COLONS).replace("\n", "\r\n"),
        "fix(agent): end the run once"
        + _BODY
        + _SCISSORS
        + "diff --git a/README.md b/README.md\n Generated with a tool\n",
        "# a comment Git adds\nfix(agent): end the run once"
        + _BODY
        + "# Please enter the message\n",
    ],
)
def test_a_message_in_the_project_form_is_accepted(tmp_path: Path, message: str) -> None:
    """Accept a Conventional Commit title followed by the three sections in order."""
    assert _refusal(tmp_path, message) is None


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Fix the agent" + _BODY, "not a Conventional Commit"),
        ("fix(agent): end the run once\n", "no Summary section"),
        ("fix(agent): end the run once\nSummary\n\nChanges\n\nVerification\n", "not blank"),
        ("fix(agent): end the run once\n\nSummary\n\nChanges\n", "no Verification section"),
        (
            "fix(agent): end the run once"
            + _BODY.replace("Verification\n", "Verification passed yesterday.\n"),
            "no Verification section",
        ),
        (
            "fix(agent): end the run once"
            + _BODY.partition("\nVerification")[0]
            + "\n"
            + _SCISSORS
            + "diff --git a/a b/a\nVerification\n",
            "no Verification section",
        ),
        (
            "fix(agent): end the run once\n\nChanges\n\nSummary\n\nVerification\n",
            "Changes section is out of order",
        ),
        (
            "fix(agent): end the run once"
            + _BODY
            + "\nCo-Authored-By: A Tool <tool@example.com>\n",
            "attribution",
        ),
        ("fix(agent): end the run once" + _BODY + "\nGenerated with a tool\n", "attribution"),
        (
            "fix(agent): end the run once" + _BODY + "\n\U0001f916 Generated with [a tool]\n",
            "attribution",
        ),
    ],
)
def test_a_message_outside_the_form_is_refused_with_its_reason(
    tmp_path: Path, message: str, reason: str
) -> None:
    """Refuse a wrong title, a missing or misplaced section and an attribution line."""
    refusal = _refusal(tmp_path, message)

    assert refusal is not None
    assert reason in refusal


def test_a_git_generated_revert_requires_the_project_form(tmp_path: Path) -> None:
    """Require the same verification record for a revert as for any other change."""
    refusal = _refusal(
        tmp_path, 'Revert "fix(agent): end the run once"\n\nThis reverts commit abc.\n'
    )

    assert refusal is not None
    assert "rewrite Git's default revert title" in refusal
    assert _refusal(tmp_path, "revert(agent): restore the previous run handling" + _BODY) is None
