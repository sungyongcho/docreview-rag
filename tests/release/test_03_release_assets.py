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
    """Bind the local UI to same-origin APIs while retaining process security guards."""
    compose = Path("docker/docker-compose.yml").read_text(encoding="utf-8")

    assert "./data:/app/data" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:\n      - ALL" in compose
    assert "${APP_PORT:-8000}:3000" in compose
    assert "${DB_PORT:-5432}:5432" in compose
    assert 'NEXT_PUBLIC_API_BASE_URL: ""' in compose
    assert "NEXT_PUBLIC_ADMIN_MODE: live" in compose
    assert "DOCREVIEW_ADMIN_MODE: live" in compose


def test_clean_checkout_script_has_fresh_locked_and_smoke_gates() -> None:
    """Gate a clean checkout on a locked sync, the focused tests, lint, and the image build."""
    script = Path("scripts/verify_clean_checkout.sh")

    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "uv sync --locked\n" in text
    assert "tests/release tests/api" in text
    assert "npm ci" in text
    assert "npm test" in text
    assert "npm run typecheck" in text
    assert "npm run build" in text
    assert "canned health and Next smoke" in text
    assert "uv run ruff check --no-fix app tests scripts" in text
    assert (
        "docker compose --project-directory . -f docker/docker-compose.yml "
        '-p "$M7_PROJECT" config --quiet' in text
    )
    assert "deploy/huggingface/Dockerfile" in text
