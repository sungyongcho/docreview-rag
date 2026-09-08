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


@pytest.fixture
def measured_cpu_inventory(monkeypatch):
    """Provide isolated Ollama metadata with controllable hardware, digest and clock."""
    state = {
        "now": 0.0,
        "digest": "d1",
        "loaded_digest": "d1",
        "loaded": True,
        "vram": 0,
        "size": 100,
    }
    monkeypatch.setattr(local_inventory, "CACHE_TTL_S", 0)
    monkeypatch.setattr(local_inventory, "monotonic", lambda: state["now"])

    def respond(request):
        """Serve metadata only; no model generation is permitted by this fixture."""
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "answer:latest", "digest": state["digest"]}]}
            )
        if request.url.path == "/api/ps":
            row = {
                "name": "answer:latest",
                "digest": state["loaded_digest"],
                "size": state["size"],
                "size_vram": state["vram"],
            }
            return httpx.Response(200, json={"models": [row] if state["loaded"] else []})
        assert request.url.path == "/api/show"
        return httpx.Response(200, json={"capabilities": ["completion"]})

    inventory = LocalModelInventory(
        base_url="http://cpu.test", transport=httpx.MockTransport(respond)
    )
    asyncio.run(inventory.snapshot())
    return inventory, state


def test_cpu_measurement_uses_generation_timings_and_preserves_server_isolation(
    measured_cpu_inventory,
):
    """Weighted Ollama generation speed ignores wall clock and unrelated provider calls."""
    inventory, _ = measured_cpu_inventory
    calls = [
        {
            "provider": "ollama",
            "model": "answer",
            "elapsed_ms": 999999,
            "local_timings": [
                {"eval_count": 100, "eval_duration_ms": 10000},
                {"eval_count": 200, "eval_duration_ms": 20000},
            ],
        },
        {
            "provider": "openai",
            "model": "answer",
            "local_timings": [{"eval_count": 999, "eval_duration_ms": 1}],
        },
        {
            "provider": "ollama",
            "model": "other",
            "local_timings": [{"eval_count": 999, "eval_duration_ms": 1}],
        },
    ]
    inventory.record_cpu_performance(
        "answer",
        {"placement": "cpu", "model": "answer:latest", "digest": "d1"},
        calls,
        model_digest="d1",
    )
    sample = asyncio.run(inventory.snapshot()).public_state()["models"][0]["cpu_performance"]
    assert sample["tokens_per_second"] == 10
    assert sample["measured_at"]
    other = LocalModelInventory(base_url="http://another.test", transport=inventory._transport)
    assert asyncio.run(other.snapshot()).models[0].cpu_performance is None
    inventory.record_cpu_performance("answer", {"reason": "unavailable"}, calls, model_digest="d1")
    assert asyncio.run(inventory.snapshot()).models[0].cpu_performance is None


@pytest.mark.parametrize(
    "change",
    [
        {"vram": 100},
        {"vram": 50},
        {"vram": None},
        {"vram": False},
        {"size": 0},
        {"loaded": False},
        {"digest": "d2"},
        {"loaded_digest": "d2"},
        {"loaded_digest": None},
        {"now": 900.0},
    ],
)
def test_cpu_measurement_is_hidden_when_hardware_identity_or_age_changes(
    measured_cpu_inventory, change
):
    """Only a recent sample for the still-loaded CPU model digest reaches readiness."""
    inventory, state = measured_cpu_inventory
    inventory.record_cpu_performance(
        "answer",
        {"placement": "cpu", "model": "answer:latest", "digest": "d1"},
        [
            {
                "provider": "ollama",
                "model": "answer",
                "local_timings": [{"eval_count": 100, "eval_duration_ms": 10000}],
            },
        ],
        model_digest="d1",
    )
    state.update(change)
    assert asyncio.run(inventory.snapshot()).models[0].cpu_performance is None


@pytest.mark.parametrize(
    "timing",
    [
        None,
        {},
        {"eval_count": True, "eval_duration_ms": 1},
        {"eval_count": 1, "eval_duration_ms": 0},
        {"eval_count": -1, "eval_duration_ms": 1},
        {"eval_count": 1, "eval_duration_ms": float("nan")},
        {"eval_count": 1, "eval_duration_ms": float("inf")},
    ],
)
def test_cpu_measurement_rejects_unusable_generation_counts(measured_cpu_inventory, timing):
    """Absent or invalid timing cannot manufacture a low-throughput warning."""
    inventory, _ = measured_cpu_inventory
    inventory.record_cpu_performance(
        "answer",
        {"placement": "cpu", "model": "answer:latest", "digest": "d1"},
        [
            {"provider": "ollama", "model": "answer", "local_timings": [timing]},
        ],
        model_digest="d1",
    )
    assert asyncio.run(inventory.snapshot()).models[0].cpu_performance is None


@pytest.mark.parametrize("loaded_digest", ["d1", "d2"])
def test_cpu_measurement_does_not_follow_a_tag_replaced_during_the_run(
    measured_cpu_inventory, loaded_digest
):
    """The run's original digest cannot be reassigned to a replacement by name."""
    inventory, state = measured_cpu_inventory
    run_digest = inventory.model_digest("answer:latest")
    assert run_digest == "d1"
    state.update(digest="d2", loaded_digest=loaded_digest)
    asyncio.run(inventory.snapshot())
    inventory.record_cpu_performance(
        "answer",
        asyncio.run(inventory.placement("answer")),
        [
            {
                "provider": "ollama",
                "model": "answer",
                "local_timings": [{"eval_count": 100, "eval_duration_ms": 10000}],
            }
        ],
        model_digest=run_digest,
    )
    assert asyncio.run(inventory.snapshot()).models[0].cpu_performance is None


@pytest.mark.parametrize("run_digest", [None, "", "d2"])
def test_cpu_measurement_requires_a_known_matching_run_digest(measured_cpu_inventory, run_digest):
    """A current matching tags/ps pair does not prove an absent or different run identity."""
    inventory, _ = measured_cpu_inventory
    inventory.record_cpu_performance(
        "answer",
        asyncio.run(inventory.placement("answer")),
        [
            {
                "provider": "ollama",
                "model": "answer",
                "local_timings": [{"eval_count": 100, "eval_duration_ms": 10000}],
            }
        ],
        model_digest=run_digest,
    )
    assert asyncio.run(inventory.snapshot()).models[0].cpu_performance is None


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (None, None),
        ({"size": 100, "size_vram": 0}, "cpu"),
        ({"size": 100, "size_vram": 100}, "gpu"),
        ({"size": 100, "size_vram": 50}, "mixed"),
        ({"size": 100}, None),
        ({"size": 0, "size_vram": 0}, None),
        ({"size": 100, "size_vram": False}, None),
    ],
)
def test_inventory_publishes_current_placement(row, expected) -> None:
    """Expose optional placement from the existing discovery probe, without inference."""
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve one model and record the bounded read-only request set."""
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "answer", "digest": "v1"}]})
        if request.url.path == "/api/ps":
            return httpx.Response(
                200, json={"models": [] if row is None else [{"name": "answer", **row}]}
            )
        assert request.url.path == "/api/show"
        return httpx.Response(200, json={"capabilities": ["completion"]})

    inventory = LocalModelInventory(
        base_url="http://localhost:11434", transport=httpx.MockTransport(respond)
    )
    snapshot = asyncio.run(inventory.snapshot())
    assert snapshot.public_state()["models"][0]["placement"] == expected
    assert sorted(calls) == ["/api/ps", "/api/show", "/api/tags"]
