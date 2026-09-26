"""Exercise documents behavior at service and HTTP boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.app import create_api_app
from app.api.documents.schemas import DocumentInventoryResponse
from tests.api.support import _admin


def test_document_query_dispatch_and_missing_detail():
    """HTTP filters reach the catalog unchanged and missing documents remain typed 404s."""
    documents = SimpleNamespace(
        documents=AsyncMock(
            return_value=DocumentInventoryResponse(documents=(), total=0, next_cursor=None)
        ),
        document_detail=AsyncMock(return_value=None),
    )
    with TestClient(create_api_app(admin_services=_admin(documents=documents))) as client:
        page = client.get(
            "/admin/documents?issuer=ACME&embedding_status=complete&snapshot_id=3&sort=embedding_coverage&descending=true"
        )
        missing = client.get("/admin/documents/unknown")
    assert page.status_code == 200
    forwarded = documents.documents.await_args.kwargs
    assert forwarded == {
        "query": "",
        "registry": "",
        "issuer": "ACME",
        "fiscal_year": None,
        "language": "",
        "form": "",
        "parse_status": "",
        "embedding_status": "complete",
        "snapshot_id": 3,
        "sort": "embedding_coverage",
        "descending": True,
        "cursor": None,
        "limit": 50,
    }
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "document_not_found"
