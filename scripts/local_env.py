"""Validate and export the host-facing local runtime environment contract."""

from __future__ import annotations

import ipaddress
from pathlib import Path
import sys

from dotenv import dotenv_values

DEFAULTS = {
    "MODE": "dev",
    "DOCREVIEW_LOCAL_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "APP_PORT": "8000",
    "DOCREVIEW_OPERATOR_WEB_PORT": "3000",
    "DOCREVIEW_OPERATOR_PORT": "18001",
    "DOCREVIEW_TUNNEL_PORT": "18000",
    "DOCREVIEW_ORIGIN_PORT": "8000",
    "DOCREVIEW_HTTP_PORT": "80",
    "DOCREVIEW_HTTPS_PORT": "443",
}
DEV_PORTS = ("DB_PORT", "APP_PORT", "DOCREVIEW_OPERATOR_WEB_PORT", "DOCREVIEW_OPERATOR_PORT")
PROD_PORTS = ("DB_PORT", "APP_PORT")


class LocalEnvironmentError(ValueError):
    """One invalid local launcher mode, host, or port contract."""


def load_local_environment(path: Path = Path(".env")) -> dict[str, str]:
    """Load defaults plus one dotenv file and validate active host bindings."""
    configured = {key: value for key, value in dotenv_values(path).items() if value is not None}
    values = DEFAULTS | configured
    mode = values["MODE"]
    if mode not in {"dev", "prod"}:
        raise LocalEnvironmentError("MODE must be dev or prod")
    host = values["DOCREVIEW_LOCAL_HOST"]
    try:
        ipaddress.ip_address(host)
    except ValueError as error:
        if host != "localhost":
            raise LocalEnvironmentError(
                "DOCREVIEW_LOCAL_HOST must be an IP address or localhost"
            ) from error
    parsed_ports: dict[str, int] = {}
    for key in DEFAULTS:
        if not key.endswith("_PORT") and key not in {"DB_PORT", "APP_PORT"}:
            continue
        try:
            value = int(values[key])
        except ValueError as error:
            raise LocalEnvironmentError(f"{key} must be an integer in 1..65535") from error
        if not 1 <= value <= 65_535:
            raise LocalEnvironmentError(f"{key} must be in 1..65535")
        parsed_ports[key] = value
    active = DEV_PORTS if mode == "dev" else PROD_PORTS
    claimed: dict[int, str] = {}
    for key in active:
        value = parsed_ports[key]
        if value in claimed:
            raise LocalEnvironmentError(
                f"host port collision: {key} and {claimed[value]} both use {value}"
            )
        claimed[value] = key
    return {key: values[key] for key in DEFAULTS}


def write_null_environment(values: dict[str, str]) -> None:
    """Write shell-safe null-delimited key/value pairs to standard output."""
    for key, value in values.items():
        sys.stdout.buffer.write(key.encode() + b"\0" + value.encode() + b"\0")


def main() -> None:
    """Validate ``.env`` and emit only the public launcher contract."""
    try:
        values = load_local_environment()
    except LocalEnvironmentError as error:
        raise SystemExit(str(error)) from error
    write_null_environment(values)


if __name__ == "__main__":
    main()
