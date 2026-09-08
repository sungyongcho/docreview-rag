"""Local settings routes, public capabilities, and production connection boundaries."""

from fastapi.testclient import TestClient
import httpx
import pytest

from app.api.runtime import RuntimeApiServices
from app.llm.local_connection import LocalConnectionManager
from app.llm.local_engine import local_provider_budget
from app.release.app import create_release_app
from app.release.config import ReleaseSettings
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def connection_app(tmp_path, environment="dev", admin_mode="live", admin_cors_origin=None):
    """Build real routes with metadata-only transport and no database calls."""

    def metadata(request: httpx.Request) -> httpx.Response:
        """Reject unreachable candidates and offer a valid empty model server otherwise."""
        if request.url.host == "offline":
            raise httpx.ConnectError("do not expose private-address", request=request)
        return httpx.Response(200, json={"models": []})

    manager = LocalConnectionManager(
        path=tmp_path / "connection.json",
        enabled=environment == "dev",
        transport=httpx.MockTransport(metadata),
    )
    runtime = RuntimeApiServices(
        embedding_provider=DeterministicEmbeddingProvider(),
        local_connection=manager,
        allow_local_engine=environment == "dev",
        llm_providers={},
        provider_budgets={
            "local": local_provider_budget(max_input_tokens=1000, max_output_tokens=100)
        },
    )
    settings = ReleaseSettings(
        _env_file=None,
        DOCREVIEW_ENVIRONMENT=environment,
        mode="runtime",
        host="127.0.0.1",
        admin_mode=admin_mode,
        admin_cors_origin=admin_cors_origin,
    )
    return create_release_app(settings, services=runtime), manager


def test_connection_routes_save_disconnect_reset_and_preserve_failed_candidate(tmp_path) -> None:
    """The web receives one stable contract for every successful connection action."""
    app, manager = connection_app(tmp_path)
    with TestClient(app) as client:
        initial = client.get("/admin/local-llm/connection")
        assert initial.status_code == 200
        assert set(initial.json()) == {
            "base_url",
            "initial_base_url",
            "protocol",
            "source",
            "error",
            "local",
            "servers",
            "selected_server_id",
        }
        saved = client.post("/admin/local-llm/connection", json={"base_url": "http://working"})
        assert saved.status_code == 200
        assert saved.json()["source"] == "saved"
        assert saved.json()["local"]["reason"] == "no_answer_models"
        old = manager.current
        failure = client.post("/admin/local-llm/connection", json={"base_url": "http://offline"})
        assert failure.status_code == 503
        assert "private-address" not in failure.text
        assert manager.current is old
        disabled = client.post("/admin/local-llm/disconnect")
        assert disabled.status_code == 200
        assert disabled.json()["source"] == "disabled"
        reset = client.post("/admin/local-llm/reset")
        assert reset.status_code == 200
        assert reset.json()["source"] == "default"


def test_public_header_hides_capabilities_and_blocks_admin_reads_and_changes(tmp_path) -> None:
    """An explicitly public browser surface cannot use the live private admin routes."""
    app, manager = connection_app(tmp_path)
    with TestClient(app) as client:
        private = client.get("/capabilities").json()
        assert private["environment"] == "dev"
        assert private["can_configure_local_llm"]
        public = client.get("/capabilities", headers={"x-docreview-public": "true"}).json()
        assert not public["can_configure_local_llm"]
        assert not public["can_edit_prompt_policy"]
        assert not public["can_use_operations"]
        response = client.get("/admin/local-llm/connection", headers={"x-docreview-public": "true"})
        assert response.status_code == 403
        response = client.post(
            "/admin/local-llm/disconnect",
            headers={"x-docreview-public": "true"},
        )
        assert response.status_code == 403
        assert manager.current.source == "default"


@pytest.mark.parametrize("admin_mode", ["live", "readonly"])
def test_prod_blocks_local_for_private_admin_and_direct_public_requests(
    tmp_path, admin_mode
) -> None:
    """Production refuses local configuration and execution even without the public header."""
    app, manager = connection_app(tmp_path, "prod", admin_mode)
    with TestClient(app) as client:
        capabilities = client.get("/capabilities").json()
        assert capabilities["environment"] == "prod"
        assert not capabilities["can_configure_local_llm"]
        for method, path in [
            ("GET", "/admin/local-llm/connection"),
            ("POST", "/admin/local-llm/disconnect"),
        ]:
            assert client.request(method, path).status_code == 403
        for path in ("/retrieve", "/review", "/review/stream"):
            response = client.post(
                path, json={"query": "hello", "session_profile": {"engine": "local"}}
            )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "disabled_in_prod"
        assert manager.current.inventory is None


def test_nonlive_public_retrieval_cannot_bypass_custom_policy_guard(tmp_path) -> None:
    """Production custom controls are blocked without relying on a client-supplied marker."""
    app, _ = connection_app(tmp_path, "prod", "readonly")
    with TestClient(app) as client:
        response = client.post(
            "/retrieve",
            json={
                "query": "question",
                "session_profile": {"prompt_policy": {"max_context_chars": 15000}},
            },
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "capability_disabled"


@pytest.mark.parametrize(
    "field,value", [("max_context_chars", 15000), ("budget", {"max_iterations": 10})]
)
def test_legacy_review_limits_cannot_bypass_public_controls(tmp_path, field, value) -> None:
    """Older clients cannot use top-level fields to evade disabled run or evidence controls."""
    app, _ = connection_app(tmp_path, "prod", "readonly")
    with TestClient(app) as client:
        response = client.post("/review", json={"query": "hello", field: value})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "capability_disabled"


@pytest.mark.parametrize(
    "action", ["connection", "disconnect", "reset", "servers", "select", "diagnostics"]
)
@pytest.mark.parametrize("origin", ["https://unrelated.example", "null", "http://localhost:9001"])
def test_browser_origin_blocks_every_local_connection_mutation(tmp_path, action, origin) -> None:
    """Simple cross-origin requests are rejected before changing active or saved settings."""
    app, manager = connection_app(tmp_path, admin_cors_origin="http://127.0.0.1:9000")
    with TestClient(app, base_url="http://app:8000") as client:
        assert (
            client.post(
                "/admin/local-llm/connection", json={"base_url": "http://working"}
            ).status_code
            == 200
        )
        previous = manager.current
        persisted = manager.path.read_bytes()
        response = client.post(
            f"/admin/local-llm/{action}",
            content="",
            headers={
                "origin": origin,
                "content-type": "text/plain",
                "x-forwarded-host": "localhost:9001",
                "x-forwarded-proto": "http",
            },
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    assert manager.current is previous
    assert manager.path.read_bytes() == persisted


@pytest.mark.parametrize("origin", ["http://localhost:9000", "http://127.0.0.1:9000"])
def test_configured_loopback_aliases_work_through_next_rewrite(tmp_path, origin) -> None:
    """The configured browser port works when Next sends the backend service Host."""
    app, _ = connection_app(tmp_path, admin_cors_origin="http://127.0.0.1:9000")
    with TestClient(app, base_url="http://app:8000") as client:
        response = client.post(
            "/admin/local-llm/disconnect",
            headers={
                "origin": origin,
                "x-forwarded-host": origin.removeprefix("http://"),
            },
        )
    assert response.status_code == 200
    assert response.json()["source"] == "disabled"


@pytest.mark.parametrize("base_url", ["http://localhost:8000", "https://127.0.0.1:8443"])
def test_actual_loopback_same_origin_does_not_need_configured_proxy_origin(
    tmp_path, base_url
) -> None:
    """Direct local browser and SSH-tunneled web requests may match the actual request origin."""
    app, _ = connection_app(tmp_path)
    with TestClient(app, base_url=base_url) as client:
        response = client.post("/admin/local-llm/disconnect", headers={"origin": base_url})
    assert response.status_code == 200


def test_forwarded_host_alone_cannot_authorize_a_browser_origin(tmp_path) -> None:
    """An untrusted forwarded host does not expand the local mutation origin allowlist."""
    app, manager = connection_app(tmp_path)
    with TestClient(app, base_url="http://app:8000") as client:
        previous = manager.current
        response = client.post(
            "/admin/local-llm/disconnect",
            headers={
                "origin": "http://localhost:9000",
                "x-forwarded-host": "localhost:9000",
                "x-forwarded-proto": "http",
            },
        )
    assert response.status_code == 403
    assert manager.current is previous


def test_named_server_and_diagnostic_routes_preserve_existing_clients_and_selection(
    tmp_path,
) -> None:
    """Named routes preserve legacy saves and the safe metadata contract."""
    app, manager = connection_app(tmp_path)
    with TestClient(app) as client:
        added = client.post(
            "/admin/local-llm/servers", json={"name": "Desk", "base_url": "http://desk"}
        )
        assert added.status_code == 200
        state = added.json()
        assert state["servers"][0]["name"] == "Default"
        assert state["servers"][1]["id"] == state["selected_server_id"]
        previous = manager.current
        original = manager.path.read_bytes()
        diagnostic = client.post("/admin/local-llm/diagnostics", json={"server_id": "default"})
        assert diagnostic.status_code == 200
        assert diagnostic.json()["server_name"] == "Default"
        assert diagnostic.json()["reachable"]
        assert not diagnostic.json()["available"]
        assert diagnostic.json()["checks"][-1]["code"] == "no_answer_models"
        assert diagnostic.json()["model_count"] == 0
        assert diagnostic.json()["answer_model_count"] == 0
        unreachable = client.post(
            "/admin/local-llm/diagnostics", json={"base_url": "http://offline"}
        )
        assert unreachable.status_code == 200
        assert unreachable.json()["model_count"] is None
        assert unreachable.json()["answer_model_count"] is None
        assert manager.current is previous
        assert manager.path.read_bytes() == original
        assert (
            client.post("/admin/local-llm/select", json={"server_id": "default"}).status_code == 200
        )
        assert manager.current.source == "default"
        saved = client.post("/admin/local-llm/connection", json={"base_url": "http://legacy"})
        assert saved.status_code == 200 and len(saved.json()["servers"]) == 3


@pytest.mark.parametrize(
    "body",
    [
        {"server_id": "default", "base_url": "http://other"},
        {"base_url": "http://user:secret@private"},
    ],
)
def test_diagnostics_reject_ambiguous_and_credential_bearing_targets(tmp_path, body) -> None:
    """Invalid diagnostic drafts never mutate the working server or persist configuration."""
    app, manager = connection_app(tmp_path)
    original = manager.current
    with TestClient(app) as client:
        response = client.post("/admin/local-llm/diagnostics", json=body)
    assert response.status_code == 422
    assert "secret" not in response.text
    assert manager.current is original
    assert not manager.path.exists()


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("servers", {"name": "Desk", "base_url": "http://desk"}),
        ("select", {"server_id": "default"}),
        ("diagnostics", {}),
    ],
)
def test_new_server_routes_remain_private_and_disabled_in_production(
    tmp_path, endpoint, payload
) -> None:
    """Neither public headers nor a production runtime can use the new local-server surface."""
    dev, dev_manager = connection_app(tmp_path)
    with TestClient(dev) as client:
        assert (
            client.post(
                f"/admin/local-llm/{endpoint}", json=payload, headers={"x-docreview-public": "true"}
            ).status_code
            == 403
        )
    prod, prod_manager = connection_app(tmp_path, "prod")
    with TestClient(prod) as client:
        assert client.post(f"/admin/local-llm/{endpoint}", json=payload).status_code == 403
    assert not dev_manager.path.exists()
    assert prod_manager.current.inventory is None


def test_prepare_route_requires_a_model_and_developer_access(tmp_path, monkeypatch):
    """Validate explicit model input and reject preparation on production surfaces."""
    app, manager = connection_app(tmp_path)
    calls = []

    async def prepare(model):
        """Return a local fixture without loading an actual server model."""
        calls.append(model)
        return await manager.state()

    monkeypatch.setattr(manager, "prepare_model", prepare)
    with TestClient(app) as client:
        assert client.post("/admin/local-llm/prepare", json={"model": "answer"}).status_code == 200
        assert calls == ["answer"]
        assert client.post("/admin/local-llm/prepare", json={"model": ""}).status_code == 422
        assert (
            client.post(
                "/admin/local-llm/prepare", json={"model": "answer", "base_url": "http://other"}
            ).status_code
            == 422
        )
    production, _ = connection_app(tmp_path / "prod", environment="prod")
    with TestClient(production) as client:
        assert client.post("/admin/local-llm/prepare", json={"model": "answer"}).status_code in {
            403,
            404,
        }
