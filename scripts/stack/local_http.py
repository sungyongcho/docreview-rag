"""Loopback HTTP shared by the local stack commands."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import OpenerDirector, ProxyHandler, build_opener


def local_opener() -> OpenerDirector:
    """Open loopback URLs directly, so a configured HTTP proxy never sees local credentials."""
    return build_opener(ProxyHandler({}))


def read_local_json(url: str, *, timeout: float, accept: tuple[int, ...] = ()) -> dict[str, Any]:
    """GET one local JSON object.

    A readiness endpoint answers 503 with its evidence in the body, so a status listed
    in ``accept`` still yields the decoded body; every other HTTP error propagates, and
    a body that is not a JSON object is a ``ValueError``.
    """
    try:
        response = local_opener().open(url, timeout=timeout)
    except HTTPError as error:
        if error.code not in accept:
            raise
        response = error
    with response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"{url} did not return a JSON object")
    return payload
