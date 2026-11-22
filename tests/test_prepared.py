"""Pin ``tests.prepared.prepared`` so unprepared live checks always skip."""

from pathlib import Path
import subprocess
import sys

import pytest

from tests.prepared import prepared

_ROOT = Path(__file__).resolve().parents[1]
_FIRST = "DOCREVIEW_PREPARED_TEST_FIRST"
_SECOND = "DOCREVIEW_PREPARED_TEST_SECOND"
_THIRD = "DOCREVIEW_PREPARED_TEST_THIRD"


def test_returns_values_as_a_tuple_in_name_order(monkeypatch: pytest.MonkeyPatch, request) -> None:
    """Return every named variable's value as a tuple in the order requested."""
    monkeypatch.setenv(_FIRST, "alpha")
    monkeypatch.setenv(_SECOND, "beta")

    values = prepared(request, _SECOND, _FIRST)

    assert type(values) is tuple
    assert values == ("beta", "alpha")


def test_unset_variable_skips_naming_it(monkeypatch: pytest.MonkeyPatch, request) -> None:
    """Skip with a message naming the variable when it is absent from the environment."""
    monkeypatch.delenv(_FIRST, raising=False)

    with pytest.raises(pytest.skip.Exception) as skipped:
        prepared(request, _FIRST)

    assert _FIRST in str(skipped.value)


def test_empty_variable_counts_as_not_set(monkeypatch: pytest.MonkeyPatch, request) -> None:
    """Skip with a message naming the variable when it is set to the empty string."""
    monkeypatch.setenv(_FIRST, "")

    with pytest.raises(pytest.skip.Exception) as skipped:
        prepared(request, _FIRST)

    assert _FIRST in str(skipped.value)


def test_partial_variables_skip_naming_only_the_missing_ones(
    monkeypatch: pytest.MonkeyPatch,
    request,
) -> None:
    """Name every unset or empty variable in the skip message, and none of the set ones."""
    monkeypatch.setenv(_FIRST, "ready")
    monkeypatch.delenv(_SECOND, raising=False)
    monkeypatch.setenv(_THIRD, "")

    with pytest.raises(pytest.skip.Exception) as skipped:
        prepared(request, _FIRST, _SECOND, _THIRD)

    message = str(skipped.value)
    assert _SECOND in message
    assert _THIRD in message
    assert _FIRST not in message


def _run_prepared_check(
    tmp_path: Path, target: str, *opts: str
) -> subprocess.CompletedProcess[str]:
    """Run one marked test through the real pytest entry point without starting services."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_path / "pytest"),
            "-q",
            "-rs",
            "-m",
            "prepared_environment",
            *opts,
            target,
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("required", [False, True])
def test_release_requires_the_requested_prepared_check_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, required: bool
) -> None:
    """A missing release image is a named skip normally and a failure at the release gate."""
    monkeypatch.delenv("DOCREVIEW_WIPE_TEST_IMAGE", raising=False)
    name = "test_disposable_compose_reset_recreates_empty_schema"
    target = f"tests/operator/reset/test_service.py::{name}"
    opts = ("--require-prepared-environment",) if required else ()

    outcome = _run_prepared_check(tmp_path, target, *opts)

    assert outcome.returncode == int(required), outcome.stdout + outcome.stderr
    assert ("1 failed" if required else "1 skipped") in outcome.stdout
    assert name in outcome.stdout
    assert "DOCREVIEW_WIPE_TEST_IMAGE" in outcome.stdout


def test_local_prod_acceptance_zero_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicitly turning off local PROD acceptance leaves the live target untouched."""
    monkeypatch.setenv("DOCREVIEW_LOCAL_PROD_ACCEPTANCE", "0")
    name = "test_prepared_local_prod_has_verified_sources_vectors_and_foreign_keys"

    outcome = _run_prepared_check(tmp_path, f"tests/scripts/stack/test_prod.py::{name}")

    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert "1 skipped" in outcome.stdout
    assert name in outcome.stdout
    assert "DOCREVIEW_LOCAL_PROD_ACCEPTANCE" in outcome.stdout
