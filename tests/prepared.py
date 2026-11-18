"""Checks that run against an environment the caller prepared beforehand.

A test marked ``prepared_environment`` reads or drives something a test run cannot
make for itself: a freshly built application image, a database restored from the
public artifacts, or the local PROD volume. The caller names that environment in the
test's own variables, and setting them is the request to run the check. Until then the
test is skipped with the variables it waits for, also under ``--require-live-postgres``:
that option speaks only for the isolated PostgreSQL of :mod:`tests.live_postgres`.
"""

import os

import pytest


def prepared(*names: str) -> tuple[str, ...]:
    """Return the values of the variables naming a prepared environment, or skip."""
    values = tuple(os.environ.get(name, "") for name in names)
    missing = [name for name, value in zip(names, values, strict=True) if not value]
    if missing:
        pytest.skip(f"Prepared environment not named: set {', '.join(missing)}")
    return values
