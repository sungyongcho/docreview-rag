"""Compose layering: a shared base, a development overlay, and a production overlay."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.release.config import ReleaseSettings

ROOT = Path(__file__).resolve().parents[2]


def compose(name: str) -> dict[str, Any]:
    """Parse one compose file, so assertions do not depend on its formatting."""
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_the_base_carries_no_local_model_wiring() -> None:
    """Local model keys live in the development overlay, so production cannot forward them."""
    environment = compose("docker-compose.yml")["services"]["app"]["environment"]

    assert not [key for key in environment if key.startswith("LOCAL_LLM")]
    assert "ollama" not in compose("docker-compose.yml")["services"]


def test_the_development_overlay_hosts_the_opt_in_model_service() -> None:
    """The model host is profiled, unpublished, and depended on by nothing."""
    dev = compose("docker-compose.dev.yml")
    ollama = dev["services"]["ollama"]

    assert ollama["profiles"] == ["local-llm"]
    assert ollama["image"] != "ollama/ollama:latest", (
        "pin the tag so a clean checkout is reproducible"
    )
    # No published port keeps this out of the launcher's host-port contract entirely.
    assert "ports" not in ollama
    assert ollama["volumes"] == ["ollama_models:/root/.ollama"]
    assert "ollama_models" in dev["volumes"]
    # A non-profiled service depending on a profiled one breaks `docker compose config`.
    assert "depends_on" not in dev["services"]["app"]

    forwarded = dev["services"]["app"]["environment"]
    assert forwarded["LOCAL_LLM_BASE_URL"] == "${LOCAL_LLM_BASE_URL:-}"
    for key in ("LOCAL_LLM_TIMEOUT_S", "LOCAL_LLM_MAX_INPUT_TOKENS", "LOCAL_LLM_MAX_OUTPUT_TOKENS"):
        assert key in forwarded


def test_the_production_overlay_reproduces_the_visitor_build() -> None:
    """A production preview bakes the public bundle and selects the production key slot."""
    app = compose("docker-compose.prod.yml")["services"]["app"]

    assert app["build"]["args"]["NEXT_PUBLIC_ADMIN_MODE"] == "canned"
    assert app["environment"]["MODE"] == "prod"
    assert app["environment"]["DOCREVIEW_ADMIN_MODE"] == "readonly"
    assert not [key for key in app["environment"] if key.startswith("LOCAL_LLM")]


def test_the_production_overlay_environment_refuses_the_local_engine(monkeypatch) -> None:
    """Even with local keys still in the developer's dotenv, MODE=prod turns the engine off."""
    monkeypatch.setenv("DOCREVIEW_MODE", "runtime")
    for key, value in compose("docker-compose.prod.yml")["services"]["app"]["environment"].items():
        monkeypatch.setenv(key, str(value))

    settings = ReleaseSettings(
        _env_file=None,
        LOCAL_LLM_BASE_URL="http://ollama:11434",
        LOCAL_LLM_MODEL="gemma4:e4b",
    )

    assert settings.local_llm_enabled is False


@pytest.mark.parametrize("name", ["docker-compose.dev.yml", "docker-compose.prod.yml"])
def test_overlays_declare_no_required_variables(name: str) -> None:
    """`docker compose config` runs on a clean checkout, where nothing is exported."""
    assert ":?" not in (ROOT / name).read_text(encoding="utf-8")


def test_the_deployment_artifact_moved_out_of_the_root() -> None:
    """The VM file lives beside the script that copies it, and forwards no local model key."""
    deploy = ROOT / "deploy" / "gcp" / "docker-compose.deploy.yml"
    script = (ROOT / "deploy" / "gcp" / "deploy_backend.sh").read_text(encoding="utf-8")

    assert deploy.exists()
    assert not (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8").count("caddy")
    assert "deploy/gcp/docker-compose.deploy.yml" in script
    assert "LOCAL_LLM" not in deploy.read_text(encoding="utf-8")
