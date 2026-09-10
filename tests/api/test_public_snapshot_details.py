"""Public evidence routes enforce bounded query inputs and stable failures."""

from fastapi.testclient import TestClient

from app.api.app import create_api_app
from app.api.deps import get_api_services
from app.api.errors import ApiProblemError
from app.api.routes import public_snapshot_details


def test_query_bounds_and_contract():
    """No provider or database is needed to validate page and search bounds."""
    application = create_api_app()
    application.dependency_overrides[get_api_services] = lambda: object()
    with TestClient(application) as client:
        for suffix in (
            "?limit=101",
            "?limit=0",
            "?offset=-1",
            "?sort=unknown",
            "?query=" + "x" * 201,
        ):
            response = client.get("/public/snapshots/1/dataset" + suffix)
            assert response.status_code == 422
        assert client.get("/public/snapshots/0/evaluation").status_code == 422
        response = client.get("/public/snapshots/1/dataset")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "snapshot_evidence_unavailable"
    schema = application.openapi()
    assert "PublicSnapshotDataset" in schema["components"]["schemas"]
    assert "PublicSnapshotEvaluation" in schema["components"]["schemas"]


def test_missing_snapshot_safe_envelope(monkeypatch):
    """Expected publication failures preserve their domain status on both routes."""

    class MissingEvidence:
        """A read seam that cannot launch retrieval or evaluate anything."""

        async def dataset(self, *args, **kwargs):
            """Report the same publication failure as the real service."""
            raise ApiProblemError(
                status_code=404, code="snapshot_not_found", message="Published snapshot not found."
            )

        evaluation = dataset

    monkeypatch.setattr(public_snapshot_details, "_details", lambda _: MissingEvidence())
    application = create_api_app()
    application.dependency_overrides[get_api_services] = lambda: object()
    with TestClient(application) as client:
        for resource in ("dataset", "evaluation"):
            response = client.get(f"/public/snapshots/1/{resource}")
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "snapshot_not_found"
