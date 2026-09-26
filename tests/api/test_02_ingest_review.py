"""M5.1 synchronous review route tests."""


def test_review_budget_exhaustion_is_a_structured_429(
    client_factory,
    services,
    budget_run,
):
    """Report budget exhaustion as a 429 carrying the limit that stopped it."""
    services.review_result = budget_run

    response = client_factory(services).post(
        "/review",
        json={
            "query": "Revenue?",
            "session_profile": {
                "prompt_policy": {"workflow_budget": {"max_iterations": 0}},
            },
        },
    )

    assert response.status_code == 429
    assert (
        services.last_review_request.session_profile.prompt_policy.workflow_budget.max_iterations
        == 0
    )
    assert response.json()["failure"] == {
        "code": "budget_exceeded",
        "resource": "iterations",
        "limit": 0,
        "observed": 0,
        "blocked_node": "retrieve",
    }


def test_review_schema_rejection_is_a_structured_502(
    client_factory,
    services,
    schema_rejected_run,
):
    """Report a rejected provider schema as a 502 naming the status."""
    services.review_result = schema_rejected_run

    response = client_factory(services).post("/review", json={"query": "Revenue?"})

    assert response.status_code == 502
    assert response.json()["failure"]["code"] == "provider_failure"
    assert response.json()["failure"]["status"] == "schema_rejected"
