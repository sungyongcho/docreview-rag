"""Container, Space metadata, and clean-verification asset tests."""

from pathlib import Path


def test_hugging_face_metadata_is_static_next_canned_and_port_aligned() -> None:
    """Declare the static service, offline mode, and one port consistently."""
    metadata = Path("deploy/huggingface/README.md").read_text(encoding="utf-8")
    dockerfile = Path("deploy/huggingface/Dockerfile").read_text(encoding="utf-8")
    environment = Path("deploy/huggingface/space.env.example").read_text(encoding="utf-8")

    assert metadata.startswith("---\n")
    assert "sdk: docker" in metadata
    assert "app_port: 7860" in metadata
    assert "DOCREVIEW_MODE=canned" in dockerfile
    assert "npm run build" in dockerfile
    assert "/web/out ./web/out" in dockerfile
    assert '--port", "7860' in dockerfile
    assert '--workers", "1' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "useradd --create-home --uid 1000 user" in dockerfile
    assert "chown user:user /home/user/app" in dockerfile
    assert "OPENAI_API_KEY=" not in environment


def test_compose_app_has_single_container_security_guards() -> None:
    """Mount only persistent data while retaining process security guards."""
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "./data:/app/data" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:\n      - ALL" in compose
    assert "${APP_PORT:-8000}:8000" in compose
    assert "${DB_PORT:-5432}:5432" in compose


def test_clean_checkout_script_has_fresh_locked_and_smoke_gates() -> None:
    """Gate a clean checkout on a locked sync, the focused tests, lint, and the image build."""
    script = Path("scripts/verify_clean_checkout.sh")

    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "uv sync --locked --extra demo" in text
    assert "tests/release tests/test_demo.py tests/api" in text
    assert "uv run ruff check --no-fix app tests scripts" in text
    assert 'docker compose -p "$M7_PROJECT" config --quiet' in text
    assert "deploy/huggingface/Dockerfile" in text
