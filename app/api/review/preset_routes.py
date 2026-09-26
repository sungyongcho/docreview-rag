"""Administrator access to local retrieval preset files."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.dependencies import AdminDependency
from app.api.errors import ApiProblemError, not_found
from app.api.review.presets import PresetCatalog, StoredPreset, effective_catalog, preset_store
from app.config import get_settings
from app.retrieval.search.profiles import with_server_bm25

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_preset_dev() -> None:
    """Keep file resources unavailable even if admin composition is enabled in PROD."""
    if get_settings().environment == "prod":
        raise not_found("presets", "directory")


@router.get("/presets", response_model=PresetCatalog)
def list_presets(services: AdminDependency, version: str | None = None) -> PresetCatalog:
    """Read a debounced catalog or return only its unchanged version."""
    _require_preset_dev()
    return effective_catalog(preset_store.catalog(version), services.runtime.bm25_parameters)


@router.put("/presets", response_model=StoredPreset)
def put_preset(preset: StoredPreset, services: AdminDependency) -> StoredPreset:
    """Atomically create or update one custom DEV preset."""
    _require_preset_dev()
    try:
        return preset_store.save(
            preset.model_copy(
                update={
                    "retrieval": with_server_bm25(
                        preset.retrieval, services.runtime.bm25_parameters
                    )
                }
            )
        )
    except ValueError as error:
        raise ApiProblemError(status_code=400, code="invalid_preset", message=str(error)) from error
    except OSError as error:
        raise ApiProblemError(
            status_code=503, code="preset_write_failed", message="Could not write the preset file."
        ) from error


@router.delete("/presets", response_model=PresetCatalog)
def delete_preset(services: AdminDependency, id: str = Query(min_length=1)) -> PresetCatalog:
    """Delete one custom DEV preset after the UI obtains confirmation."""
    _require_preset_dev()
    try:
        preset_store.delete(id)
    except ValueError as error:
        raise ApiProblemError(status_code=400, code="invalid_preset", message=str(error)) from error
    except FileNotFoundError as error:
        raise not_found("preset", id) from error
    except OSError as error:
        raise ApiProblemError(
            status_code=503, code="preset_write_failed", message="Could not delete the preset file."
        ) from error
    return effective_catalog(preset_store.catalog(), services.runtime.bm25_parameters)
