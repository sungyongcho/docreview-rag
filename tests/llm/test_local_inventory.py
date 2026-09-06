"""Read-only discovery, bounded caching, and model capability checks."""

import asyncio
import json

import httpx
import pytest

import app.llm.local_inventory as local_inventory
from app.llm.local_inventory import LocalModelInventory


def test_discovery_filters_embeddings_and_reuses_details(monkeypatch) -> None:
    """Concurrent readers share probes while changed digests refresh only their metadata."""
    calls = []
    digest = "v1"
    now = 0.0
    monkeypatch.setattr(local_inventory, "monotonic", lambda: now)

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve inventory metadata without allowing any inference or download request."""
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer private-test-key"
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "answer", "digest": digest, "size": 123},
                        {"name": "embed", "digest": "e1"},
                    ]
                },
            )
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "answer"}]})
        assert request.url.path == "/api/show"
        model = json.loads(request.content)["model"]
        return httpx.Response(
            200,
            json={
                "capabilities": ["completion"] if model == "answer" else ["embedding"],
                "details": {"parameter_size": "4B", "quantization_level": "Q4_K_M"},
            },
        )

    inventory = LocalModelInventory(
        base_url="http://private-host:11435",
        api_key="private-test-key",
        transport=httpx.MockTransport(respond),
    )

    async def exercise() -> None:
        """Exercise concurrent reads, expiry, and a single changed model."""
        nonlocal now, digest
        first, second = await asyncio.gather(inventory.snapshot(), inventory.snapshot())
        assert first is second
        assert first.available_models == ("answer",)
        assert first.models[0].loaded is True
        assert first.models[1].loaded is False
        assert first.models[0].size_bytes == 123
        assert first.models[0].parameter_size == "4B"
        assert "private" not in json.dumps(first.public_state())
        assert len(calls) == 4
        now = 11
        await inventory.snapshot()
        assert len(calls) == 6
        now = 22
        digest = "v2"
        await inventory.snapshot()
        assert len(calls) == 9

    asyncio.run(exercise())


@pytest.mark.parametrize("models", [[], [{"name": "embed", "digest": "e1"}]])
def test_inventory_without_answer_models_is_unavailable(models) -> None:
    """An empty inventory or embedding-only server cannot enable answer selection."""

    def respond(request: httpx.Request) -> httpx.Response:
        """Return only embedding capabilities from the installed model server."""
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["embedding"]})
        return httpx.Response(200, json={"models": models})

    inventory = LocalModelInventory(base_url="http://host", transport=httpx.MockTransport(respond))
    snapshot = asyncio.run(inventory.snapshot())
    assert snapshot.reason == "no_answer_models"
    assert snapshot.public_state()["enabled"] is False


def test_server_disconnect_and_recovery_do_not_reuse_stale_availability(monkeypatch) -> None:
    """A failed refresh clears availability, and a later probe recovers it."""
    monkeypatch.setattr(local_inventory, "CACHE_TTL_S", 0)
    online = True

    def respond(request: httpx.Request) -> httpx.Response:
        """Expose one OpenAI-compatible model only while the endpoint is online."""
        assert request.url.path == "/v1/models"
        if not online:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json={"data": [{"id": "answer"}]})

    inventory = LocalModelInventory(
        base_url="http://host/v1", transport=httpx.MockTransport(respond)
    )

    async def exercise() -> None:
        """Change connection state between successive requests."""
        nonlocal online
        assert (await inventory.snapshot()).available_models == ("answer",)
        online = False
        failed = await inventory.snapshot()
        assert failed.reason == "unreachable"
        assert failed.models == ()
        online = True
        recovered = await inventory.snapshot()
        assert recovered.available_models == ("answer",)
        assert recovered.models[0].capabilities is None

    asyncio.run(exercise())


def test_missing_optional_details_are_not_invented() -> None:
    """Unavailable capabilities disable that model while unknown load state stays unknown."""

    def respond(request: httpx.Request) -> httpx.Response:
        """Fail optional metadata endpoints after returning an installed model."""
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "answer"}]})
        return httpx.Response(503)

    inventory = LocalModelInventory(base_url="http://host", transport=httpx.MockTransport(respond))
    model = asyncio.run(inventory.snapshot()).models[0]
    assert not model.selectable
    assert model.capabilities is None
    assert model.loaded is None


def test_probe_deadline_bounds_a_stalled_server(monkeypatch) -> None:
    """A slow metadata server cannot stall readiness beyond the total probe deadline."""
    monkeypatch.setattr(local_inventory, "PROBE_TIMEOUT_S", 0.02)

    async def respond(request: httpx.Request) -> httpx.Response:
        """Stay blocked until the inventory's total deadline cancels the request."""
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    inventory = LocalModelInventory(base_url="http://host", transport=httpx.MockTransport(respond))
    assert asyncio.run(inventory.snapshot()).reason == "unreachable"


@pytest.mark.parametrize("payload", [{"models": None}, {"models": [{"name": 12}]}])
def test_malformed_inventory_fails_closed(payload) -> None:
    """Malformed server data is unavailable rather than a fabricated empty success."""
    inventory = LocalModelInventory(
        base_url="http://host",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    assert asyncio.run(inventory.snapshot()).reason == "unreachable"


@pytest.mark.parametrize("vram,expected", [(0, "cpu"), (50, "mixed"), (100, "gpu")])
def test_placement_reads_reported_memory_without_inference(vram, expected):
    """Only GET /api/ps is allowed, and no missing value is interpreted as zero."""

    def respond(request):
        """Expose one loaded model without accepting any mutation or inference."""
        assert request.method == "GET" and request.url.path == "/api/ps"
        return httpx.Response(
            200, json={"models": [{"name": "answer:latest", "size": 100, "size_vram": vram}]}
        )

    inventory = LocalModelInventory(
        base_url="http://host:11434", transport=httpx.MockTransport(respond)
    )
    assert asyncio.run(inventory.placement("answer"))["placement"] == expected


@pytest.mark.parametrize(
    "models,reason",
    [
        ([], "model_not_loaded"),
        ([{"name": "answer", "size": 100}], "ollama_memory_fields_unavailable"),
    ],
)
def test_placement_explains_missing_evidence(models, reason):
    """An unloaded model and missing memory telemetry remain distinct outcomes."""
    inventory = LocalModelInventory(
        base_url="http://host:11434",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"models": models})),
    )
    assert asyncio.run(inventory.placement("answer")) == {"reason": reason}
