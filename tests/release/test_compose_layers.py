"""Compose layering: a shared base, a development overlay, and a production overlay."""

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from app.release.config import ReleaseSettings
from tests.support import load_settings

ROOT = Path(__file__).resolve().parents[2]


def compose(name: str, overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """Render the actual Compose merge without loading developer credentials or starting Docker."""
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(ROOT),
        "--env-file",
        os.devnull,
        "-f",
        str(ROOT / "docker" / "docker-compose.yml"),
    ]
    if name != "docker-compose.yml":
        command += ["-f", str(ROOT / "docker" / name)]
    environment = {
        key: os.environ[key] for key in ("PATH", "HOME", "DOCKER_CONFIG") if key in os.environ
    }
    environment.update(overrides or {})
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_the_default_stack_needs_no_compose_file_environment_switch() -> None:
    """Plain Compose includes source-mounted development and an optional external model endpoint."""
    base = compose("docker-compose.yml")
    assert set(base["services"]) == {"app", "db", "web"}
    database = base["services"]["db"]
    assert database["image"] == "pgvector/pgvector:pg16"
    assert any(
        mount["type"] == "volume"
        and mount["source"] == "pg_data"
        and mount["target"] == "/var/lib/postgresql/data"
        for mount in database["volumes"]
    )
    assert database["ports"][0]["published"] == "5432"
    assert database["ports"][0]["target"] == 5432
    assert "ollama_models" not in base["volumes"]
    app = base["services"]["app"]
    assert app["environment"]["DATABASE_URL"] == "postgresql+asyncpg://filing:filing@db:5432/filing"
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert app["cap_drop"] == ["ALL"]
    assert any(
        mount["type"] == "bind"
        and mount["source"] == str(ROOT / "data")
        and mount["target"] == "/app/data"
        for mount in app["volumes"]
    )
    assert app["build"]["args"]["NEXT_PUBLIC_API_BASE_URL"] == ""
    assert app["build"]["args"]["NEXT_PUBLIC_ADMIN_MODE"] == "live"
    assert app["environment"]["LOCAL_LLM_BASE_URL"] == "http://host.docker.internal:11434"
    assert "LOCAL_LLM_MODEL" not in app["environment"]
    assert app["extra_hosts"] == ["host.docker.internal=host-gateway"]


def test_explicit_development_inherits_the_default_mounts_and_services() -> None:
    """The optional dev selection preserves the default stack and explicitly selects dev roles."""
    base = compose("docker-compose.yml")
    dev = compose("docker-compose.dev.yml")
    assert dev["services"]["web"] == base["services"]["web"]
    for key in ("volumes", "command", "extra_hosts"):
        assert dev["services"]["app"][key] == base["services"]["app"][key]
    assert dev["services"]["app"]["environment"]["MODE"] == "dev"
    assert dev["services"]["app"]["environment"]["DOCREVIEW_ADMIN_MODE"] == "live"


def test_the_production_overlay_reproduces_the_visitor_build() -> None:
    """A production preview bakes the public bundle and selects the production key slot."""
    config = compose("docker-compose.prod.yml")
    assert set(config["services"]) == {"app", "db", "web"}
    app = config["services"]["app"]

    assert app["build"]["args"]["NEXT_PUBLIC_ADMIN_MODE"] == "canned"
    assert app["environment"]["MODE"] == "prod"
    assert app["environment"]["DOCREVIEW_ADMIN_MODE"] == "readonly"
    assert not [key for key in app["environment"] if key.startswith("LOCAL_LLM")]


def test_the_production_overlay_environment_refuses_the_local_engine(monkeypatch) -> None:
    """Even with local keys still in the developer's dotenv, MODE=prod turns the engine off."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    for key, value in compose("docker-compose.prod.yml")["services"]["app"]["environment"].items():
        monkeypatch.setenv(key, str(value))

    settings = load_settings(
        ReleaseSettings,
        env_file=None,
        LOCAL_LLM_BASE_URL="http://ollama:11434",
    )

    assert settings.local_llm_enabled is False


def test_development_mounts_source_and_keeps_browser_dependencies_separate() -> None:
    """Code reloads in development without exposing backend secrets to the web service."""
    dev = compose("docker-compose.dev.yml")
    web = dev["services"]["web"]
    assert web["image"] == "node:24-alpine"
    assert any(v["type"] == "bind" and v["target"] == "/web" for v in web["volumes"])
    assert any(v["type"] == "volume" and v["target"] == "/web/node_modules" for v in web["volumes"])
    assert any(v["type"] == "volume" and v["target"] == "/web/.next" for v in web["volumes"])
    assert "env_file" not in web
    assert "depends_on" not in web
    assert set(web["environment"]) <= {
        "NEXT_PUBLIC_ADMIN_MODE",
        "NEXT_PUBLIC_API_BASE_URL",
        "NEXT_PUBLIC_DB_ENDPOINT",
        "NEXT_PUBLIC_OPERATOR_BASE_URL",
        "NEXT_PUBLIC_OPERATOR_TOKEN",
        "DOCREVIEW_API_UPSTREAM",
        "DOCREVIEW_LOCAL_HOST",
        "DOCREVIEW_SCREENSHOT_MODE",
    }
    assert web["environment"]["NEXT_PUBLIC_API_BASE_URL"] == "/docreview-rag/api"
    assert web["environment"]["DOCREVIEW_API_UPSTREAM"] == "http://app:8000"
    assert not dev["services"]["app"].get("ports")
    assert web["ports"][0]["published"] == "8000"
    assert web["ports"][0]["target"] == 3000
    assert any(
        v["target"] == "/app/app" and v["read_only"] for v in dev["services"]["app"]["volumes"]
    )
    assert "--reload" in dev["services"]["app"]["command"]
    prod = compose("docker-compose.prod.yml")
    assert prod["services"]["web"]["volumes"] == web["volumes"]
    assert prod["services"]["app"]["command"] == dev["services"]["app"]["command"]
    # The base data mount stays; the local-prod overlay adds its own corpus, evaluation
    # and runtime directories and a separate database volume.
    assert {v["target"] for v in prod["services"]["app"]["volumes"]} == {
        "/app/app",
        "/app/data",
        "/app/data/corpus",
        "/app/data/eval_runs",
        "/app/data/runtime",
    }
    assert set(prod["volumes"]) == {"prod_pg_data", "web_node_modules", "web_next"}
    assert prod["services"]["web"]["environment"]["NEXT_PUBLIC_ADMIN_MODE"] == "canned"
    assert prod["services"]["web"]["environment"]["NEXT_PUBLIC_OPERATOR_TOKEN"] == ""
    assert not prod["services"]["app"].get("extra_hosts")


@pytest.mark.parametrize(
    "name, mode, admin, web_admin",
    [
        ("docker-compose.yml", "dev", "live", "live"),
        ("docker-compose.dev.yml", "dev", "live", "live"),
        ("docker-compose.prod.yml", "prod", "readonly", "canned"),
    ],
)
def test_mode_and_frontend_routing_ignore_stale_shell_flags(name, mode, admin, web_admin) -> None:
    """Explicit Compose contracts override old dotenv or exported mode controls."""
    config = compose(
        name,
        {
            "MODE": "prod" if mode == "dev" else "dev",
            "DOCREVIEW_ADMIN_MODE": "live",
            "NEXT_PUBLIC_ADMIN_MODE": "readonly",
            "NEXT_PUBLIC_API_BASE_URL": "http://wrong.example",
            "APP_PORT": "19000",
        },
    )
    app = config["services"]["app"]
    web = config["services"]["web"]
    assert app["environment"]["MODE"] == mode
    assert app["environment"]["DOCREVIEW_ADMIN_MODE"] == admin
    assert web["environment"]["NEXT_PUBLIC_ADMIN_MODE"] == web_admin
    assert web["environment"]["NEXT_PUBLIC_API_BASE_URL"] == "/docreview-rag/api"
    assert web["ports"][0]["published"] == "19000"
    assert not app.get("ports")


def test_compose_modes_inherit_the_image_schema_gate() -> None:
    """Dev, preview and deployment must not bypass the image's initialization entrypoint."""
    dockerfile = (ROOT / "docker/Dockerfile").read_text()
    assert 'ENTRYPOINT ["/app/.venv/bin/python", "-m", "app.db.startup"]' in dockerfile
    for name in ("docker-compose.dev.yml", "docker-compose.prod.yml"):
        app = compose(name)["services"]["app"]
        assert app.get("entrypoint") is None
        assert app["depends_on"]["db"]["condition"] == "service_healthy"
        assert app["environment"]["DOCREVIEW_MODE"] == "runtime"
    deployed = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "--env-file",
                os.devnull,
                "-f",
                str(ROOT / "deploy/gcp/docker-compose.deploy.yml"),
                "config",
                "--format",
                "json",
            ],
            env={
                "PATH": os.environ["PATH"],
                "DOCREVIEW_IMAGE": "example.invalid/test:fixture",
                "POSTGRES_PASSWORD": "unused-fixture",
                "OPENAI_API_KEY_PROD": "unused-fixture",
                "DOCREVIEW_ORIGIN_HOST": "localhost",
                "POSTGRES_PASSWORD_FILE": os.devnull,
            },
            text=True,
        )
    )
    app = deployed["services"]["app"]
    assert app.get("entrypoint") is None
    assert app["depends_on"]["db"]["condition"] == "service_healthy"
    assert app["environment"]["DOCREVIEW_MODE"] == "runtime"


def test_local_app_shares_host_group_and_writable_creation_mask() -> None:
    """Local file creation retains the non-root image UID and the inherited schema gate."""
    app = compose("docker-compose.dev.yml", {"HOST_GID": "2345"})["services"]["app"]
    assert app["user"] == "10001:2345"
    assert app.get("entrypoint") is None
    assert app["command"][:4] == ["sh", "-c", 'umask 0002; exec "$$@"', "--"]
    assert app["command"][4:7] == ["uv", "run", "--no-sync"]
    assert app["tmpfs"] == ["/tmp"]
