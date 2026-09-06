"""Persist named model servers with immutable active request snapshots."""

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import TypeAdapter

from app.llm.local_diagnostics import remediation_ids
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


@dataclass(frozen=True)
class LocalServer:
    """One administrator-named endpoint, independent of the selected answer model."""

    id: str
    name: str
    base_url: str
    protocol: LocalProtocol


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
        self.initial_protocol: LocalProtocol = initial_protocol
        self.initial_source: ConnectionSource = initial_source
        self._api_key = api_key
        self._transport = transport
        self._lock = asyncio.Lock()
        self._servers: tuple[LocalServer, ...] = ()
        self._selected_server_id: str | None = "default" if enabled else None
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

    def _default_server(self) -> LocalServer:
        """Resolve Default through the configured runtime address, including Docker defaults."""
        return LocalServer("default", "Default", self.initial_base_url, self.initial_protocol)

    def _server(self, server_id: str) -> LocalServer:
        """Resolve a registered identifier without accepting a new endpoint implicitly."""
        if server_id == "default":
            return self._default_server()
        server = next((item for item in self._servers if item.id == server_id), None)
        if server is None:
            raise ValueError("Select an available local server.")
        return server

    @staticmethod
    def _server_name(name: str) -> str:
        """Require a readable private label without shadowing the built-in Default entry."""
        normalized = name.strip()
        if not normalized or len(normalized) > 80 or normalized.casefold() == "default":
            raise ValueError("Enter a server name of 1–80 characters other than Default.")
        return normalized

    def _load(self) -> LocalConnection:
        """Reject invalid persisted state rather than falling back to another endpoint."""
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict) or data.get("version") not in {1, 2}:
            raise ValueError("invalid local connection settings")
        if data["version"] == 2:
            rows = data.get("servers")
            if not isinstance(rows, list):
                raise ValueError("invalid saved local servers")
            servers = []
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("id"), str)
                    or not row["id"]
                    or row["id"] == "default"
                    or not isinstance(row.get("name"), str)
                    or not isinstance(row.get("base_url"), str)
                    or row.get("protocol") not in {"auto", "ollama", "openai_responses"}
                ):
                    raise ValueError("invalid saved local server")
                servers.append(
                    LocalServer(
                        row["id"],
                        self._server_name(row["name"]),
                        validate_base_url(row["base_url"]),
                        row["protocol"],
                    )
                )
            if len({row.id for row in servers}) != len(servers) or len(
                {row.name.casefold() for row in servers}
            ) != len(servers):
                raise ValueError("duplicate saved local server")
            self._servers = tuple(servers)
        state = data.get("state")
        if state == "initial":
            self._selected_server_id = "default"
            return self._initial_connection()
        if state == "disabled":
            selected = data.get("selected_server_id", "default")
            self._selected_server_id = (
                self._server(selected).id if selected is not None else "default"
            )
            return LocalConnection(None, self.initial_protocol, "disabled", None)
        if data["version"] == 2 and state == "connected":
            selected_id = data.get("selected_server_id")
            if not isinstance(selected_id, str):
                raise ValueError("invalid selected local server")
            server = self._server(selected_id)
            self._selected_server_id = server.id
            return self._connection(
                server.base_url,
                server.protocol,
                self.initial_source if server.id == "default" else "saved",
            )
        if state != "connected" or not isinstance(data.get("base_url"), str):
            raise ValueError("invalid local connection settings")
        protocol = TypeAdapter(LocalProtocol).validate_python(
            data.get("protocol", "auto"), strict=True
        )
        normalized = validate_base_url(data["base_url"])
        if normalized == self.initial_base_url and protocol == self.initial_protocol:
            self._selected_server_id = "default"
            return self._initial_connection()
        server = LocalServer("legacy", "Saved server", normalized, protocol)
        self._servers = (server,)
        self._selected_server_id = server.id
        return self._connection(normalized, protocol, "saved")

    def _persist(self, data: dict[str, object]) -> None:
        """Atomically replace the saved choice before making it active in memory."""
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.path.parent, prefix=".local-llm-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump({"version": 2, **data}, stream)
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
                    "servers": [
                        {**asdict(item), "is_default": item.id == "default"}
                        for item in (self._default_server(), *self._servers)
                    ],
                    "selected_server_id": self._selected_server_id,
                }

    def _saved_state(
        self, state: str, selected: str | None, servers: tuple[LocalServer, ...] | None = None
    ) -> dict[str, object]:
        """Serialize a complete candidate configuration before changing runtime state."""
        return {
            "state": state,
            "selected_server_id": selected,
            "servers": [asdict(item) for item in (self._servers if servers is None else servers)],
        }

    async def _activate(
        self, server: LocalServer, servers: tuple[LocalServer, ...] | None = None
    ) -> None:
        """Probe and persist under the caller's lock before replacing the active revision."""
        candidate = self._connection(
            server.base_url,
            server.protocol,
            self.initial_source if server.id == "default" else "saved",
        )
        assert candidate.inventory is not None
        snapshot = await candidate.inventory.snapshot()
        if snapshot.reason not in {None, "no_answer_models"}:
            raise LocalConnectionError(
                "local_connection_failed",
                "The model server could not be reached or returned invalid model information.",
            )
        self._persist(self._saved_state("connected", server.id, servers))
        if servers is not None:
            self._servers = servers
        self._selected_server_id = server.id
        self._active = candidate

    async def connect(self, base_url: str, protocol: LocalProtocol = "auto") -> dict[str, Any]:
        """Verify a candidate, then persist and activate it without replacing on failure."""
        self._require_enabled()
        async with self._lock:
            normalized = validate_base_url(base_url)
            server = next(
                (
                    item
                    for item in (self._default_server(), *self._servers)
                    if item.base_url == normalized and item.protocol == protocol
                ),
                None,
            )
            servers = self._servers
            if server is None:
                name = "Saved server"
                index = 2
                while any(item.name.casefold() == name.casefold() for item in servers):
                    name = f"Saved server {index}"
                    index += 1
                server = LocalServer(str(uuid4()), name, normalized, protocol)
                servers = (*servers, server)
            await self._activate(server, servers)
        return await self.state()

    async def add_server(
        self, name: str, base_url: str, protocol: LocalProtocol = "auto"
    ) -> dict[str, Any]:
        """Register and select a verified named server atomically without losing saved choices."""
        self._require_enabled()
        async with self._lock:
            normalized_name = self._server_name(name)
            normalized_url = validate_base_url(base_url)
            if any(item.name.casefold() == normalized_name.casefold() for item in self._servers):
                raise ValueError("A server with this name is already registered.")
            if any(
                item.base_url == normalized_url and item.protocol == protocol
                for item in (self._default_server(), *self._servers)
            ):
                raise ValueError(
                    "This server is already registered. Select it from the server list."
                )
            server = LocalServer(str(uuid4()), normalized_name, normalized_url, protocol)
            await self._activate(server, (*self._servers, server))
        return await self.state()

    async def select_server(self, server_id: str) -> dict[str, Any]:
        """Verify a registered server or Default before activating its immutable connection."""
        self._require_enabled()
        async with self._lock:
            await self._activate(self._server(server_id))
        return await self.state()

    async def diagnose(
        self,
        *,
        server_id: str | None = None,
        base_url: str | None = None,
        protocol: LocalProtocol = "auto",
    ) -> dict[str, Any]:
        """Probe independent metadata without saving, selecting, loading, or generating a model."""
        self._require_enabled()
        if server_id is not None and base_url is not None:
            raise ValueError("Choose a registered server or a draft URL, not both.")
        selected = server_id if server_id is not None else self._selected_server_id
        if base_url is not None:
            server = LocalServer("", "Draft server", validate_base_url(base_url), protocol)
        elif selected is not None and self.current.source not in {"invalid", "disabled"}:
            server = self._server(selected)
        elif server_id is not None:
            server = self._server(server_id)
        else:
            code = "invalid" if self.current.source == "invalid" else "disconnected"
            selected_server = (
                self._server(selected) if selected is not None else self._default_server()
            )
            return {
                "checked_at": datetime.now(UTC).isoformat(),
                "server_id": selected_server.id,
                "server_name": selected_server.name,
                "protocol": selected_server.protocol,
                "reachable": None,
                "available": False,
                "model_count": None,
                "answer_model_count": None,
                "models": [],
                "checks": [
                    {
                        "id": "configuration",
                        "status": "blocked",
                        "code": code,
                        "remediation": remediation_ids(code),
                    }
                ],
            }
        candidate = self._connection(server.base_url, server.protocol, "saved")
        assert candidate.inventory is not None
        snapshot = await candidate.inventory.snapshot()
        reachable = snapshot.reason != "unreachable"
        code = "reachable" if reachable else snapshot.failure_code or "connection"
        model_code = (
            "unconfirmed"
            if not reachable
            else "answer_models_available"
            if snapshot.available_models
            else "no_answer_models"
        )
        return {
            "checked_at": snapshot.checked_at,
            "server_id": server.id or None,
            "server_name": server.name,
            "protocol": snapshot.protocol,
            "reachable": reachable,
            "available": bool(snapshot.available_models),
            "model_count": len(snapshot.models) if reachable else None,
            "answer_model_count": len(snapshot.available_models) if reachable else None,
            "models": [asdict(item) for item in snapshot.models],
            "checks": [
                {
                    "id": "configuration",
                    "status": "passed",
                    "code": "configured",
                    "remediation": [],
                },
                {
                    "id": "connection",
                    "status": "passed" if reachable else "failed",
                    "code": code,
                    "remediation": [] if reachable else remediation_ids(code),
                },
                {
                    "id": "models",
                    "status": "unknown"
                    if not reachable
                    else "passed"
                    if snapshot.available_models
                    else "blocked",
                    "code": model_code,
                    "remediation": remediation_ids(model_code)
                    if model_code == "no_answer_models"
                    else [],
                },
            ],
        }

    async def disconnect(self) -> dict[str, Any]:
        """Persist an explicit off state so defaults cannot silently reconnect."""
        self._require_enabled()
        async with self._lock:
            self._persist(self._saved_state("disabled", self._selected_server_id))
            self._active = LocalConnection(None, self.initial_protocol, "disabled", None)
        return await self.state()

    async def reset(self) -> dict[str, Any]:
        """Restore startup settings and let ordinary readiness report reachability."""
        self._require_enabled()
        async with self._lock:
            candidate = self._initial_connection()
            self._persist(self._saved_state("initial", "default"))
            self._selected_server_id = "default"
            self._active = candidate
        return await self.state()
