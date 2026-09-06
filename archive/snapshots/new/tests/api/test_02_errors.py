"""M5.1 typed validation, domain, and unexpected error responses."""

from tests.support import need


def test_unconfigured_service_returns_typed_503(A, client_factory):
    need(A, "create_api_app")
    response = client_factory().post("/retrieve", json={"query": "Revenue?"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "API services are not configured.",
            "details": [],
        }
    }


def test_malformed_json_returns_typed_422_without_a_traceback(client_factory, services):
    response = client_factory(services).post(
        "/retrieve",
        content=b'{"query":',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "request_validation_failed"
    assert body["error"]["details"]
    assert "traceback" not in response.text.lower()


def test_empty_query_returns_typed_422(client_factory, services):
    response = client_factory(services).post("/retrieve", json={"query": " "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_failed"
    assert services.last_retrieve_request is None


def test_expected_domain_problem_returns_typed_400(A, client_factory, services):
    need(A, "bad_request")
    services.retrieve_error = A.bad_request("invalid_query", "The query is not supported.")

    response = client_factory(services).post("/retrieve", json={"query": "Revenue?"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_query"


def test_unexpected_service_failure_returns_non_leaking_500(client_factory, services):
    services.retrieve_error = RuntimeError("secret database details")

    response = client_factory(services).post("/retrieve", json={"query": "Revenue?"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret database details" not in response.text
    assert "traceback" not in response.text.lower()
