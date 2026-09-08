"""Exercise real JSON persistence, cache invalidation and admin route boundaries."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.api.app import create_api_app
from app.api.preset_store import BUILTIN_IDS, DEFAULT_PRESET_DIRECTORY, PresetStore, StoredPreset
from app.api.review_profile import (
    CustomRetrievalProfile,
    ReviewSessionProfile,
    resolve_retrieval_profile,
)


@pytest.fixture
def store(tmp_path: Path) -> PresetStore:
    """Seed only canonical built-ins in a disposable directory."""
    for identity in BUILTIN_IDS:
        (tmp_path / f"{identity}.json").write_bytes(
            (DEFAULT_PRESET_DIRECTORY / f"{identity}.json").read_bytes()
        )
    return PresetStore(tmp_path)


def custom(identity: str = "research", k: int = 5) -> StoredPreset:
    """Build a valid independently named custom preset."""
    return StoredPreset(
        id=identity,
        name=identity.title(),
        description="Research",
        retrieval=CustomRetrievalProfile(k=k),
    )


def test_create_update_delete_and_builtins(store: PresetStore):
    """Round-trip metadata and prevent modifications to reserved files."""
    saved = store.save(custom())
    payload = json.loads((store.directory / "research.json").read_text())
    assert payload["updated_at"] == saved.updated_at
    assert payload["description"] == "Research"
    store.save(custom(k=8))
    assert next(p for p in store.catalog().presets if p.id == "research").retrieval.k == 8
    for preset in store.catalog().presets:
        if preset.builtin:
            with pytest.raises(ValueError, match="copied"):
                store.save(preset)
            with pytest.raises(ValueError, match="reserved"):
                store.delete(preset.id)
    store.delete("research")
    assert not (store.directory / "research.json").exists()
    with pytest.raises(ValueError):
        store.delete("../outside")


def test_corrupt_and_changed_files_debounce_without_rereading_unchanged(store: PresetStore):
    """Metadata checks reuse bytes until changed files settle; corruption stays visible."""
    with patch("app.api.preset_store.time.monotonic", return_value=1):
        initial = store.catalog()
        (store.directory / "research.json").write_text(custom().model_dump_json())
        assert store.catalog().presets_version == initial.presets_version
    with patch("app.api.preset_store.time.monotonic", return_value=1.3):
        changed = store.catalog()
        assert any(p.id == "research" for p in changed.presets)
    with patch.object(Path, "read_text", side_effect=AssertionError("unchanged files reread")):
        assert store.catalog(changed.presets_version).unchanged
    (store.directory / "research.json").write_text('{"invalid":')
    corrupt = store.catalog(force=True)
    assert [e.file for e in corrupt.errors] == ["research.json"]
    assert len(corrupt.presets) == 3
    (store.directory / "research.json").write_text(custom(k=9).model_dump_json())
    assert not store.catalog(force=True).errors
    (store.directory / "research.json").unlink()
    assert len(store.catalog(force=True).presets) == 3


def test_atomic_failure_preserves_previous_bytes(store: PresetStore):
    """A failed replacement leaves the previous valid preset and no temporary file."""
    store.save(custom())
    before = (store.directory / "research.json").read_bytes()
    with patch("app.api.preset_store.os.replace", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError):
            store.save(custom(k=8))
    assert (store.directory / "research.json").read_bytes() == before
    assert not list(store.directory.glob(".preset-*"))


def test_server_resolves_canonical_files(store: PresetStore):
    """Named request profiles match the exact canonical JSON shipped to the web."""
    for preset in store.catalog().presets:
        resolved = resolve_retrieval_profile(ReviewSessionProfile(retrieval_preset=preset.id))
        assert resolved.model_dump(exclude={"preset"}) == preset.retrieval.model_dump()


def test_admin_api_validation_and_production_boundary(store: PresetStore):
    """Only an injected DEV admin surface exposes validated file operations."""
    with TestClient(create_api_app()) as client:
        assert client.get("/admin/presets").status_code == 404
    with (
        patch("app.api.routes.admin.preset_store", store),
        patch("app.api.routes.admin.get_settings", return_value=SimpleNamespace(environment="dev")),
        TestClient(create_api_app(admin_services=object())) as client,
    ):
        initial = client.get("/admin/presets").json()
        assert client.get("/admin/presets", params={"version": initial["presets_version"]}).json()[
            "unchanged"
        ]
        assert client.put("/admin/presets", json=custom().model_dump()).status_code == 200
        malformed = custom().model_dump()
        malformed["retrieval"]["candidate_k"] = 1
        assert client.put("/admin/presets", json=malformed).status_code == 422
        assert client.delete("/admin/presets", params={"id": "balanced"}).status_code == 400
        assert client.delete("/admin/presets", params={"id": "research"}).status_code == 200
        with patch(
            "app.api.routes.admin.get_settings", return_value=SimpleNamespace(environment="prod")
        ):
            assert client.get("/admin/presets").status_code == 404
            assert client.put("/admin/presets", json=custom().model_dump()).status_code == 404
            assert client.delete("/admin/presets", params={"id": "research"}).status_code == 404


def test_hand_written_file_infers_identity_from_filename(store: PresetStore):
    """Hand-written files need name and retrieval; the filename supplies their ID."""
    (store.directory / "handwritten.json").write_text(
        json.dumps({"name": "Handwritten", "retrieval": CustomRetrievalProfile().model_dump()})
    )
    assert next(p for p in store.catalog().presets if p.id == "handwritten").name == "Handwritten"
