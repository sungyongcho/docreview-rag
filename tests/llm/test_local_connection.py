"""Persisted endpoint selection, guarded discovery, and atomic configuration updates."""

import asyncio
import json

import httpx
import pytest

import app.llm.local_connection as connections
from app.llm.local_connection import LocalConnectionError, LocalConnectionManager, validate_base_url


def metadata_server(request: httpx.Request) -> httpx.Response:
    """Serve bounded model metadata without accepting load, download, or inference calls."""
    if request.url.host == "offline":
        raise httpx.ConnectError("private-host-address", request=request)
    assert request.url.path in {"/api/tags", "/api/ps", "/api/show", "/v1/models"}
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "answer"}]})
    if request.url.path == "/api/show":
        return httpx.Response(200, json={"capabilities": ["completion"]})
    models = [] if request.url.host == "empty" else [{"name": "answer", "digest": "same"}]
    return httpx.Response(200, json={"models": models})


def test_saved_connection_restart_disconnect_and_reset(tmp_path) -> None:
    """Saved choices survive restart; explicit off stays off and reset restores startup."""
    path = tmp_path / "connection.json"
    transport = httpx.MockTransport(metadata_server)
    manager = LocalConnectionManager(
        initial_base_url="http://initial:11434",
        initial_source="environment",
        path=path,
        transport=transport,
    )

    async def exercise() -> None:
        """Use the same on-disk configuration across independent runtime instances."""
        assert (await manager.state())["source"] == "environment"
        saved = await manager.connect("http://replacement:11435")
        assert saved["source"] == "saved"
        assert saved["local"]["enabled"]
        restarted = LocalConnectionManager(
            initial_base_url="http://initial:11434",
            initial_source="environment",
            path=path,
            transport=transport,
        )
        assert restarted.current.base_url == "http://replacement:11435"
        await restarted.disconnect()
        disabled = LocalConnectionManager(path=path, transport=transport)
        assert disabled.current.source == "disabled"
        assert (await disabled.public_state()) == {"enabled": False, "reason": "disabled"}
        restored = await restarted.reset()
        assert restored["source"] == "environment"
        assert restored["base_url"] == "http://initial:11434"
        assert LocalConnectionManager(path=path).current.source == "default"

    asyncio.run(exercise())


def test_failed_probe_and_failed_save_keep_the_existing_revision(tmp_path, monkeypatch) -> None:
    """Neither connectivity nor atomic-write failure can replace the currently working server."""
    path = tmp_path / "connection.json"
    manager = LocalConnectionManager(path=path, transport=httpx.MockTransport(metadata_server))

    async def exercise() -> None:
        """Compare both runtime identity and persisted bytes around failed updates."""
        await manager.connect("http://working")
        old = manager.current
        contents = path.read_bytes()
        with pytest.raises(LocalConnectionError, match="could not be reached"):
            await manager.connect("http://offline")
        assert manager.current is old
        assert path.read_bytes() == contents

        def fail_replace(*args) -> None:
            """Represent a filesystem that cannot atomically commit the new settings."""
            raise OSError("private filesystem detail")

        monkeypatch.setattr(connections.os, "replace", fail_replace)
        with pytest.raises(LocalConnectionError, match="Could not save"):
            await manager.connect("http://replacement")
        assert manager.current is old
        assert path.read_bytes() == contents
        assert list(tmp_path.iterdir()) == [path]

    asyncio.run(exercise())


def test_empty_server_is_a_valid_connection_and_changed_url_does_not_get_secret(tmp_path) -> None:
    """Server reachability is separate from answer availability, and credentials stay at origin."""
    seen = []

    def record(request: httpx.Request) -> httpx.Response:
        """Capture only headers for the exact endpoint used by each probe."""
        seen.append((request.url.host, request.headers.get("authorization")))
        return metadata_server(request)

    manager = LocalConnectionManager(
        initial_base_url="http://original",
        api_key="initial-secret",
        path=tmp_path / "setting.json",
        transport=httpx.MockTransport(record),
    )

    async def exercise() -> None:
        """Probe the initial endpoint, then save a distinct server with no installed models."""
        await manager.state()
        result = await manager.connect("http://empty")
        assert result["source"] == "saved"
        assert result["local"]["reason"] == "no_answer_models"
        assert not result["local"]["enabled"]
        assert all(auth == "Bearer initial-secret" for host, auth in seen if host == "original")
        assert all(auth is None for host, auth in seen if host == "empty")
        assert "initial-secret" not in manager.path.read_text()
        assert "original" not in json.dumps(result["local"])

    asyncio.run(exercise())


def test_corrupt_file_fails_closed_and_prod_does_not_read_or_probe(tmp_path, monkeypatch) -> None:
    """Invalid stored settings do not fall back, and prod does not even read them."""
    path = tmp_path / "broken.json"
    path.write_text("not json")
    manager = LocalConnectionManager(path=path, transport=httpx.MockTransport(metadata_server))
    assert manager.current.source == "invalid"
    assert manager.current.inventory is None

    def forbid(*args, **kwargs):
        """Fail if production accesses the connection file or model server."""
        raise AssertionError("production read or probe")

    monkeypatch.setattr(connections.Path, "exists", forbid)
    manager = LocalConnectionManager(
        enabled=False, path=path, transport=httpx.MockTransport(forbid)
    )
    assert asyncio.run(manager.public_state()) == {"enabled": False, "reason": "disabled_in_prod"}
    with pytest.raises(LocalConnectionError, match="disabled in production"):
        asyncio.run(manager.connect("http://other"))


def test_late_old_readiness_cannot_overwrite_new_connection(tmp_path) -> None:
    """A pending metadata read returns the active connection after a concurrent switch."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        """Delay the old server until the new setting has become active."""
        if request.url.host == "old":
            started.set()
            await release.wait()
        return metadata_server(request)

    manager = LocalConnectionManager(
        initial_base_url="http://old/v1",
        path=tmp_path / "connection.json",
        transport=httpx.MockTransport(respond),
    )

    async def exercise() -> None:
        """Switch servers while an existing readiness request is waiting."""
        pending = asyncio.create_task(manager.state())
        await started.wait()
        await manager.connect("http://replacement/v1")
        release.set()
        state = await pending
        assert state["base_url"] == "http://replacement/v1"
        assert state["source"] == "saved"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host",
        "http://user:password@host",
        "http://host?key=secret",
        "http://host#fragment",
        "no-host",
    ],
)
def test_invalid_or_credential_bearing_urls_are_rejected(url) -> None:
    """Only plain absolute HTTP endpoints can be persisted or probed."""
    with pytest.raises(ValueError):
        validate_base_url(url)


@pytest.mark.parametrize(
    "url,port", [("http://host", None), ("https://host", None), ("https://host:11435", 11435)]
)
def test_explicit_schemes_and_ports_are_preserved(url, port) -> None:
    """Explicit ports are preserved and omitted ports are not replaced with Ollama port 11434."""
    assert httpx.URL(validate_base_url(url)).port == port


@pytest.mark.parametrize("state", ["connected", "disabled"])
def test_saved_choice_overrides_invalid_initial_url(tmp_path, state) -> None:
    """An invalid initial URL cannot disable a saved choice or leak credentials."""
    path = tmp_path / "connection.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "state": state,
                "base_url": "http://saved",
                "protocol": "ollama",
            }
        )
    )
    manager = LocalConnectionManager(
        initial_base_url="http://user:secret@invalid",
        path=path,
        api_key="initial-secret",
        transport=httpx.MockTransport(metadata_server),
    )
    original_bytes = path.read_bytes()
    previous = manager.current
    assert previous.source == ("saved" if state == "connected" else "disabled")
    if previous.inventory is not None:
        assert previous.inventory.api_key is None
    response = asyncio.run(manager.state())
    assert "secret" not in json.dumps(response)
    assert response["initial_base_url"] == ""
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        asyncio.run(manager.reset())
    assert manager.current is previous
    assert path.read_bytes() == original_bytes


def test_invalid_initial_url_is_reported_when_no_saved_choice_exists(tmp_path) -> None:
    """Initial validation remains fail-closed when no higher-priority configuration applies."""
    manager = LocalConnectionManager(initial_base_url="not-a-url", path=tmp_path / "missing.json")
    assert manager.current.source == "invalid"
    assert manager.current.inventory is None
