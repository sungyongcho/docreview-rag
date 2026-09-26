"""The Hugging Face Space image must build from files this checkout still has."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]


def test_space_dockerfile_copies_only_existing_documentation_sources():
    """Every ``COPY docs/...`` source exists, and the story pages the web build reads are among
    them, so the release stage that builds the image cannot fail on a deleted document."""
    dockerfile = (ROOT / "deploy/huggingface/Dockerfile").read_text(encoding="utf-8")
    sources = [
        source
        for line in dockerfile.splitlines()
        if line.startswith("COPY docs/")
        for source in line.split()[1:-1]
    ]

    assert sources, "the image copies no documentation"
    missing = [source for source in sources if not (ROOT / source).exists()]
    assert missing == []
    registry = (ROOT / "web/lib/documentation-registry.mjs").read_text(encoding="utf-8")
    story_files = re.findall(r'"\.\./(DEVELOPMENT_STORY\.[a-z]{2}\.md)"', registry)
    assert story_files, "the documentation registry names no story pages"
    assert {f"docs/{name}" for name in story_files} <= set(sources)
