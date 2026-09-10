"""Swagger documentation remains complete without enabling administrator routes."""

from typing import cast

from fastapi.testclient import TestClient

from app.api.admin_deps import get_admin_services
from app.api.admin_runtime import RuntimeAdminApiServices
from app.api.app import create_api_app


def test_read_only_docs_include_admin_contracts_without_exposing_handlers() -> None:
    """Production documentation describes every operation but mounts no admin handler."""
    application = create_api_app(enable_docs_execution=False, include_admin_schema=True)
    dev_application = create_api_app(
        admin_services=cast(RuntimeAdminApiServices, object()),
    )
    expected_schema = dev_application.openapi()

    with TestClient(application) as client:
        docs = client.get("/docs")
        response = client.get("/openapi.json")
        assert docs.status_code == 200
        assert '"supportedSubmitMethods": []' in docs.text
        assert '"tryItOutEnabled": false' in docs.text
        assert response.status_code == 200
        schema = response.json()
        assert schema["paths"] == expected_schema["paths"]
        assert schema["components"] == expected_schema["components"]
        assert "/admin/corpus/jobs" in schema["paths"]
        assert client.get("/admin/corpus").status_code == 404
        assert client.put("/admin/presets", json={}).status_code == 404

    assert get_admin_services not in application.dependency_overrides


def test_documented_schema_includes_later_application_routes() -> None:
    """Factory callers can still add release routes before or after schema generation."""
    application = create_api_app(include_admin_schema=True)
    initial_schema = application.openapi()
    assert application.openapi() is initial_schema

    @application.get("/release-status")
    def release_status() -> dict[str, str]:
        """Expose a small route to exercise the application composition boundary."""
        return {"status": "ok"}

    schema = application.openapi()
    assert "/release-status" in schema["paths"]
    assert "/admin/corpus/jobs" in schema["paths"]
    assert application.openapi() is schema


def test_default_docs_preserve_swagger_execution() -> None:
    """Development Swagger retains its normal request execution controls."""
    with TestClient(create_api_app()) as client:
        docs = client.get("/docs")

    assert docs.status_code == 200
    assert '"supportedSubmitMethods": []' not in docs.text
