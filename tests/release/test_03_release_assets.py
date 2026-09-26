"""Hugging Face Space metadata and container asset tests."""

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
