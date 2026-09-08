"""Local JSON retrieval presets with atomic writes and a debounced metadata cache."""

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
import time
from typing import Annotated

from pydantic import Field, StrictBool, model_validator

from app.api.review_profile import CustomRetrievalProfile, StrictProfileModel

BUILTIN_IDS = frozenset({"balanced", "korean", "accuracy"})
DEFAULT_PRESET_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "presets"


class StoredPreset(StrictProfileModel):
    """One portable preset; its ID must match its safe JSON filename."""

    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")]
    name: Annotated[str, Field(min_length=1, max_length=80)]
    retrieval: CustomRetrievalProfile
    description: Annotated[str, Field(max_length=2000)] = ""
    builtin: StrictBool = False
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> StoredPreset:
        """Reserve built-in identities and reject blank display names."""
        if not self.name.strip():
            raise ValueError("Use a preset name of 1–80 characters.")
        if self.builtin != (self.id in BUILTIN_IDS):
            raise ValueError("Built-in preset identities are reserved.")
        return self


class PresetFileError(StrictProfileModel):
    """A corrupt filename remains visible while other presets stay usable."""

    file: str
    error: str


class PresetCatalog(StrictProfileModel):
    """Versioned directory snapshot; unchanged reads omit the catalog payload."""

    presets_version: str
    unchanged: bool = False
    presets: list[StoredPreset] = Field(default_factory=list)
    errors: list[PresetFileError] = Field(default_factory=list)


class PresetStore:
    """Scan metadata on refresh, debounce edits and only reread changed JSON files."""

    def __init__(self, directory: Path = DEFAULT_PRESET_DIRECTORY, debounce_s: float = 0.2):
        """Keep cache and write serialization isolated to this local directory."""
        self.directory = directory
        self.debounce_s = debounce_s
        self._lock = RLock()
        self._signature: tuple = ()
        self._pending: tuple = ()
        self._pending_since = 0.0
        self._files: dict[str, tuple[tuple, StoredPreset | PresetFileError]] = {}
        self._catalog: PresetCatalog | None = None

    def catalog(self, version: str | None = None, *, force: bool = False) -> PresetCatalog:
        """Return a stable snapshot after metadata changes have settled."""
        with self._lock:
            signature = []
            for path in sorted(self.directory.glob("*.json")):
                try:
                    stat = path.lstat()
                    signature.append((path.name, stat.st_mtime_ns, stat.st_size, stat.st_ino))
                except FileNotFoundError:
                    continue
            current = tuple(signature)
            now = time.monotonic()
            if current != self._pending:
                self._pending, self._pending_since = current, now
            if (
                self._catalog is None
                or force
                or (current != self._signature and now - self._pending_since >= self.debounce_s)
            ):
                files = {}
                for metadata in current:
                    name = metadata[0]
                    if self._files.get(name, (None,))[0] == metadata:
                        files[name] = self._files[name]
                        continue
                    path = self.directory / name
                    try:
                        if path.is_symlink():
                            raise ValueError("Symbolic links are not supported.")
                        if metadata[2] > 64_000:
                            raise ValueError("Preset files must not exceed 64 KB.")
                        payload = json.loads(path.read_text())
                        if isinstance(payload, dict):
                            payload.setdefault("id", path.stem)
                        preset = StoredPreset.model_validate(payload)
                        if preset.id != path.stem:
                            raise ValueError("Preset ID must match the JSON filename.")
                        entry = preset
                    except (OSError, ValueError) as error:
                        entry = PresetFileError(file=name, error=str(error))
                    files[name] = (metadata, entry)
                errors = [
                    entry for _, entry in files.values() if isinstance(entry, PresetFileError)
                ]
                presets = [entry for _, entry in files.values() if isinstance(entry, StoredPreset)]
                for missing in sorted(
                    BUILTIN_IDS - {p.id for p in presets} - {Path(e.file).stem for e in errors}
                ):
                    errors.append(
                        PresetFileError(
                            file=f"{missing}.json", error="Built-in preset file is missing."
                        )
                    )
                self._catalog = PresetCatalog(
                    presets_version=hashlib.sha256(repr(current).encode()).hexdigest()[:20],
                    presets=presets,
                    errors=errors,
                )
                self._files, self._signature = files, current
            catalog = self._catalog
            if version == catalog.presets_version:
                return PresetCatalog(presets_version=catalog.presets_version, unchanged=True)
            return catalog

    def save(self, preset: StoredPreset) -> StoredPreset:
        """Validate before replacing one file atomically; preserve prior bytes on failure."""
        with self._lock:
            if preset.builtin:
                raise ValueError("Built-in presets can only be copied.")
            if any(
                p.id != preset.id and p.name.strip().casefold() == preset.name.strip().casefold()
                for p in self.catalog(force=True).presets
            ):
                raise ValueError("A preset with this name already exists.")
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{preset.id}.json"
            if target.is_symlink():
                raise ValueError("Symbolic links are not supported.")
            saved = preset.model_copy(
                update={"name": preset.name.strip(), "updated_at": datetime.now(UTC).isoformat()}
            )
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", dir=self.directory, prefix=".preset-", delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    stream.write(saved.model_dump_json(indent=2) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self.catalog(force=True)
            return saved

    def delete(self, identity: str) -> None:
        """Remove only a validated custom preset ID, never a built-in or another path."""
        with self._lock:
            StoredPreset(id=identity, name="Delete", retrieval=CustomRetrievalProfile())
            target = self.directory / f"{identity}.json"
            if target.is_symlink():
                raise ValueError("Symbolic links are not supported.")
            target.unlink()
            self.catalog(force=True)


preset_store = PresetStore()
