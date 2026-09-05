"""Persist one administrator-selected model endpoint with immutable request snapshots."""

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Literal

import httpx

from app.llm.local_inventory import LocalModelInventory
from app.settings_sources import DEFAULT_LOCAL_BASE_URL

LocalProtocol = Literal["auto", "ollama", "openai_responses"]
ConnectionSource = Literal["saved", "environment", "dotenv", "default", "disabled", "invalid"]
DEFAULT_CONNECTION_FILE = Path("data/local-settings/local-llm.json")


class LocalConnectionError(ValueError):
    """A safe connection failure suitable for an administrator response."""

    def __init__(self, code: str, message: str) -> None:
        """Keep provider addresses and operating-system error details out of messages."""
        super().__init__(message)
        self.code = code


def validate_base_url(value: str) -> str:
    """Accept only absolute HTTP endpoints without embedded authentication or query data."""
    try:
        url = httpx.URL(value.strip())
    except httpx.InvalidURL as error:
        raise ValueError("Enter a valid HTTP or HTTPS server URL.") from error
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Use an HTTP or HTTPS server URL without credentials, query, or fragment.")
    return str(url).rstrip("/")


@dataclass(frozen=True)
class LocalConnection:
    """A connection revision that remains valid for requests already in progress."""

    base_url: str | None
    protocol: LocalProtocol
    source: ConnectionSource
    inventory: LocalModelInventory | None
    error: str | None = None


class LocalConnectionManager:
    """Own runtime endpoint changes without changing in-flight provider identities."""

    def __init__(
        self,
        *,
        initial_base_url: str | None = DEFAULT_LOCAL_BASE_URL,
        initial_protocol: LocalProtocol = "auto",
        initial_source: ConnectionSource = "default",
        api_key: str | None = None,
        enabled: bool = True,
        path: Path = DEFAULT_CONNECTION_FILE,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Load only local configuration in dev; construction never contacts a model server."""
        self.enabled = enabled
        self.path = path
        self.initial_base_url = initial_base_url or DEFAULT_LOCAL_BASE_URL
        self.initial_protocol = initial_protocol
        self.initial_source = initial_source
        self._api_key = api_key
        self._transport = transport
        self._lock = asyncio.Lock()
        self._active = LocalConnection(None, initial_protocol, "disabled", None)
        if not enabled:
            return
        try:
            self.initial_base_url = validate_base_url(self.initial_base_url)
        except ValueError:
            # Invalid lower-priority input must not hide a valid saved choice or expose
            # credentials in the settings response. Reset still validates this value.
            self.initial_base_url = ""
        try:
            self._active = self._load() if self.path.exists() else self._initial_connection()
        except PermissionError:
            self._active = LocalConnection(
                None,
                initial_protocol,
                "invalid",
                None,
                "Local connection settings are not readable by this runtime user. "
                "Check the settings file and directory ownership.",
            )
        except OSError, ValueError, TypeError:
            self._active = LocalConnection(
                None,
                initial_protocol,
                "invalid",
                None,
                "Stored or initial local connection settings are invalid. Save a valid URL.",
            )

    @property
    def current(self) -> LocalConnection:
        """Capture one immutable endpoint revision before starting request work."""
        return self._active

    def _connection(
        self, base_url: str, protocol: LocalProtocol, source: ConnectionSource
    ) -> LocalConnection:
        """Attach environment credentials only to the original configured endpoint."""
        normalized = validate_base_url(base_url)
        inventory = LocalModelInventory(
            base_url=normalized,
            protocol=protocol,
            api_key=self._api_key if normalized == self.initial_base_url else None,
            transport=self._transport,
        )
        return LocalConnection(normalized, protocol, source, inventory)

    def _initial_connection(self) -> LocalConnection:
        """Resolve the configured startup values independently of persisted overrides."""
        return self._connection(self.initial_base_url, self.initial_protocol, self.initial_source)

    def _load(self) -> LocalConnection:
        """Reject invalid persisted state rather than falling back to another endpoint."""
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("invalid local connection settings")
        state = data.get("state")
        if state == "initial":
            return self._initial_connection()
        if state == "disabled":
            return LocalConnection(None, self.initial_protocol, "disabled", None)
        if state != "connected" or not isinstance(data.get("base_url"), str):
            raise ValueError("invalid local connection settings")
        protocol = data.get("protocol", "auto")
        if protocol not in {"auto", "ollama", "openai_responses"}:
            raise ValueError("invalid local connection protocol")
        return self._connection(data["base_url"], protocol, "saved")

    def _persist(self, data: dict[str, object]) -> None:
        """Atomically replace the saved choice before making it active in memory."""
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.path.parent, prefix=".local-llm-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump({"version": 1, **data}, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except PermissionError as error:
            raise LocalConnectionError(
                "local_connection_save_failed",
                "Could not save local connection settings. The settings directory is not "
                "writable by this runtime user; check its ownership.",
            ) from error
        except OSError as error:
            raise LocalConnectionError(
                "local_connection_save_failed", "Could not save local connection settings."
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _require_enabled(self) -> None:
        """Block every configuration or probe operation when running in production."""
        if not self.enabled:
            raise LocalConnectionError("disabled_in_prod", "Local LLM is disabled in production.")

    async def public_state(self) -> dict[str, Any]:
        """Read metadata from the latest endpoint without returning endpoint details."""
        if not self.enabled:
            return {"enabled": False, "reason": "disabled_in_prod"}
        while True:
            connection = self.current
            if connection.inventory is None:
                return {"enabled": False, "reason": connection.source}
            state = (await connection.inventory.snapshot()).public_state()
            if connection is self.current:
                return state

    async def state(self) -> dict[str, Any]:
        """Return private administrator settings and their current public model metadata."""
        self._require_enabled()
        while True:
            connection = self.current
            local = await self.public_state()
            if connection is self.current:
                return {
                    "base_url": connection.base_url,
                    "initial_base_url": self.initial_base_url,
                    "protocol": connection.protocol,
                    "source": connection.source,
                    "error": connection.error,
                    "local": local,
                }

    async def connect(self, base_url: str, protocol: LocalProtocol = "auto") -> dict[str, Any]:
        """Verify a candidate, then persist and activate it without replacing on failure."""
        self._require_enabled()
        async with self._lock:
            candidate = self._connection(base_url, protocol, "saved")
            assert candidate.inventory is not None
            snapshot = await candidate.inventory.snapshot()
            if snapshot.reason not in {None, "no_answer_models"}:
                raise LocalConnectionError(
                    "local_connection_failed",
                    "The model server could not be reached or returned invalid model information.",
                )
            self._persist(
                {"state": "connected", "base_url": candidate.base_url, "protocol": protocol}
            )
            self._active = candidate
        return await self.state()

    async def disconnect(self) -> dict[str, Any]:
        """Persist an explicit off state so defaults cannot silently reconnect."""
        self._require_enabled()
        async with self._lock:
            self._persist({"state": "disabled"})
            self._active = LocalConnection(None, self.initial_protocol, "disabled", None)
        return await self.state()

    async def reset(self) -> dict[str, Any]:
        """Restore startup settings and let ordinary readiness report reachability."""
        self._require_enabled()
        async with self._lock:
            candidate = self._initial_connection()
            self._persist({"state": "initial"})
            self._active = candidate
        return await self.state()
