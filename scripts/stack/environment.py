"""Validate the host-facing values for an explicitly selected local mode."""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import sys

from dotenv import dotenv_values

DEFAULTS = {
    "DOCREVIEW_LOCAL_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "APP_PORT": "8000",
    "DOCREVIEW_OPERATOR_PORT": "18001",
    "DOCREVIEW_TUNNEL_PORT": "18000",
    "DOCREVIEW_ORIGIN_PORT": "8000",
    "DOCREVIEW_HTTP_PORT": "80",
    "DOCREVIEW_HTTPS_PORT": "443",
}
DEV_PORTS = ("DB_PORT", "APP_PORT", "DOCREVIEW_OPERATOR_PORT")
PROD_PORTS = ("DB_PORT", "APP_PORT")


class LocalEnvironmentError(ValueError):
    """One invalid local launcher mode, host, or port contract."""


def load_local_environment(path: Path = Path(".env"), *, mode: str = "dev") -> dict[str, str]:
    """Load only public bindings while keeping mode selection outside dotenv."""
    if mode not in {"dev", "prod"}:
        raise LocalEnvironmentError("mode must be dev or prod")
    configured = {key: value for key, value in dotenv_values(path).items() if value is not None}
    values = {key: configured.get(key, default) for key, default in DEFAULTS.items()}
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
    return values | {"MODE": mode}


def write_null_environment(values: dict[str, str]) -> None:
    """Write shell-safe null-delimited key/value pairs to standard output."""
    for key, value in values.items():
        sys.stdout.buffer.write(key.encode() + b"\0" + value.encode() + b"\0")


def main() -> None:
    """Emit only the validated public launcher contract for the selected mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dev", "prod"), default="dev")
    args = parser.parse_args()
    try:
        values = load_local_environment(mode=args.mode)
    except LocalEnvironmentError as error:
        raise SystemExit(str(error)) from error
    write_null_environment(values)


if __name__ == "__main__":
    main()
