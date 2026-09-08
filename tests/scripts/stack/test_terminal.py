"""Verify quiet and verbose subprocess output using short disposable child processes."""

import subprocess
import sys

import pytest

from scripts.stack.terminal import run_step


@pytest.mark.parametrize("verbose", [False, True])
def test_step_output_visibility_and_elapsed_time(tmp_path, monkeypatch, capsys, verbose):
    """Quiet mode suppresses command noise while verbosity streams it under the step."""
    monkeypatch.setenv("DOCREVIEW_VERBOSE", "1" if verbose else "0")
    monkeypatch.setenv("NO_COLOR", "1")
    run_step("Build images", [sys.executable, "-c", "print('build-log')"], cwd=tmp_path)
    output = capsys.readouterr().out
    assert "[ OK ] Build images" in output and "s\n" in output
    assert ("build-log" in output) == verbose
    assert "\x1b" not in output


def test_failure_prints_only_bounded_tail_and_exact_rerun(tmp_path, monkeypatch, capsys):
    """A failing quiet step retains useful final lines and reports the executable invocation."""
    monkeypatch.delenv("DOCREVIEW_VERBOSE", raising=False)
    command = [
        sys.executable,
        "-c",
        "for i in range(40): print('line-' + str(i))\nraise SystemExit(7)",
    ]
    with pytest.raises(subprocess.CalledProcessError) as caught:
        run_step("Build images", command, cwd=tmp_path)
    assert caught.value.returncode == 7
    output = capsys.readouterr()
    assert "[FAIL] Build images" in output.out
    assert "line-39\n" in output.err and "line-0\n" not in output.err
    assert "Rerun: env DOCREVIEW_VERBOSE=1" in output.err
