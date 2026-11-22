"""Checks that run against an environment the caller prepared beforehand.

A test marked ``prepared_environment`` reads or drives something a test run cannot
make for itself: a freshly built application image, a database restored from the
public artifacts, or the local PROD volume. The caller names that environment in the
test's own variables. An unprepared test skips with its name and the variables it
needs. Use ``--require-prepared-environment`` when selected checks must run.
"""

import os

import pytest


def prepared(
    request: pytest.FixtureRequest, *names: str, disabled_value: str | None = None
) -> tuple[str, ...]:
    """Read prepared variables, treating an explicit off value as unprepared."""
    values = tuple(os.environ.get(name, "") for name in names)
    missing = [
        name
        for name, value in zip(names, values, strict=True)
        if not value or value == disabled_value
    ]
    if missing:
        pytest.skip(f"{request.node.nodeid}: prepared environment requires {', '.join(missing)}")
    return values
