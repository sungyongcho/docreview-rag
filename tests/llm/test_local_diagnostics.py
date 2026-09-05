"""Transport classification and actionable nonsecret diagnostic guidance."""

import httpx
import pytest

from app.llm.local_diagnostics import failure_kind, remediation_ids


@pytest.mark.parametrize(
    "error,code,remedy",
    [
        (httpx.ConnectError("getaddrinfo secret-host"), "dns", "check_network"),
        (httpx.ConnectError("Connection refused secret-host"), "refused", "check_listener"),
        (httpx.ConnectError("SSL certificate secret-host"), "tls", "review_tls"),
        (httpx.ReadTimeout("secret-host"), "timeout", "check_network"),
        (ValueError("secret response"), "invalid_response", "review_protocol"),
    ],
)
def test_transport_failure_guidance_never_contains_the_raw_error(error, code, remedy) -> None:
    """Classify real failure types while returning only stable codes and manual action IDs."""
    assert failure_kind(error) == code
    assert remedy in remediation_ids(code)
    assert "secret" not in " ".join([code, *remediation_ids(code)])


@pytest.mark.parametrize(
    "status,code", [(401, "authentication"), (403, "authentication"), (404, "http_404")]
)
def test_http_status_failures_keep_the_status_without_response_content(status, code) -> None:
    """Authentication and route failures remain distinguishable without leaking server bodies."""
    response = httpx.Response(status, request=httpx.Request("GET", "http://private"), text="secret")
    with pytest.raises(httpx.HTTPStatusError) as caught:
        response.raise_for_status()
    assert failure_kind(caught.value) == code
