"""Safe transport classification shared by local-server Web and CLI diagnostics."""

import httpx


def failure_kind(error: Exception) -> str:
    """Classify metadata failures without returning URLs, credentials, or exception text."""
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        return "authentication" if code in {401, 403} else f"http_{code}"
    if isinstance(error, httpx.TimeoutException | TimeoutError):
        return "timeout"
    if isinstance(error, httpx.InvalidURL):
        return "invalid_url"
    if isinstance(error, ValueError):
        return "invalid_response"
    description = str(error).lower()
    if any(part in description for part in ("certificate", "ssl", "tls")):
        return "tls"
    if any(part in description for part in ("name or service", "name resolution", "getaddrinfo")):
        return "dns"
    if "refused" in description:
        return "refused"
    return "connection"


def remediation_ids(code: str) -> list[str]:
    """Return stable guidance identifiers, never executable server-supplied content."""
    return {
        "disconnected": ["select_server"],
        "invalid": ["select_server"],
        "dns": ["check_network", "run_connection_diagnostics"],
        "refused": ["check_ollama_service", "check_listener", "run_connection_diagnostics"],
        "timeout": ["check_network", "check_ollama_service", "run_connection_diagnostics"],
        "tls": ["review_tls"],
        "authentication": ["review_credentials"],
        "invalid_url": ["review_protocol"],
        "invalid_response": ["review_protocol"],
        "no_answer_models": ["check_ollama_models"],
    }.get(code, ["check_network", "review_protocol", "run_connection_diagnostics"])
