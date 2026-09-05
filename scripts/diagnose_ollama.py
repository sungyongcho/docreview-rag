"""Diagnose the active web-to-model connection without changing any service or model."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values
import httpx


def failure_kind(error: httpx.HTTPError) -> str:
    """Classify a transport failure without emitting URLs or secret-bearing exception text."""
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code in {401, 403}:
            return "authentication"
        return f"http_{code}"
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    description = str(error).lower()
    if "certificate" in description or "ssl" in description or "tls" in description:
        return "tls"
    if (
        "name or service" in description
        or "name resolution" in description
        or "getaddrinfo" in description
    ):
        return "dns"
    if "refused" in description:
        return "refused"
    return "connection"


def valid_url(value: str) -> str:
    """Require a credential-free HTTP URL before invoking any HTTP client."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an HTTP/HTTPS server URL without credentials, query, or fragment.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("The server port must be in 1..65535.")
    return value.strip().rstrip("/")


def probe_url(
    base_url: str,
    protocol: str = "auto",
    *,
    transport: httpx.MockTransport | None = None,
) -> dict[str, Any]:
    """Probe metadata from the current process namespace, never loading or generating a model."""
    # This branch also protects probes executed inside a production app container.
    if os.environ.get("MODE", os.environ.get("DOCREVIEW_ENVIRONMENT", "dev")) == "prod":
        return {"status": "disabled", "reason": "disabled_in_prod"}
    from app.llm.local_engine import resolve_local_protocol
    from app.llm.local_inventory import LocalModelInventory

    try:
        root = valid_url(base_url)
    except ValueError:
        return {"status": "unreachable", "reason": "invalid_url"}
    resolved = resolve_local_protocol(root, protocol)
    initial = os.environ.get(
        "LOCAL_LLM_BASE_URL", os.environ.get("DOCREVIEW_LOCAL_LLM_BASE_URL", "")
    )
    api_key = None
    if initial.strip().rstrip("/") == root:
        api_key = os.environ.get("LOCAL_LLM_API_KEY") or os.environ.get(
            "DOCREVIEW_LOCAL_LLM_API_KEY"
        )
    headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    path = (
        "/api/tags" if resolved == "ollama" else "/models" if root.endswith("/v1") else "/v1/models"
    )
    try:
        with httpx.Client(timeout=2, transport=transport, follow_redirects=False) as client:
            response = client.get(f"{root}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()
        field = "models" if resolved == "ollama" else "data"
        if not isinstance(payload, dict) or not isinstance(payload.get(field), list):
            return {"status": "unreachable", "reason": "invalid_response"}
    except httpx.HTTPError as error:
        return {"status": "unreachable", "reason": failure_kind(error)}
    except ValueError:
        return {"status": "unreachable", "reason": "invalid_response"}
    inventory = LocalModelInventory(
        base_url=root, protocol=resolved, api_key=api_key, transport=transport
    )
    snapshot = asyncio.run(inventory.snapshot())
    return {"status": "reachable", "local": snapshot.public_state()}


def container_probe(root: Path, url: str, protocol: str) -> dict[str, Any]:
    """Execute the same read-only metadata probe in the already running app container."""
    if shutil.which("docker") is None:
        return {"status": "unconfirmed", "reason": "docker_missing"}
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "-p",
        root.name,
        "-f",
        str(root / "docker" / "docker-compose.yml"),
        "exec",
        "-T",
        "app",
        "/app/.venv/bin/python",
        "-",
        "--probe",
        url,
        "--protocol",
        protocol,
    ]
    try:
        result = subprocess.run(
            command,
            input=Path(__file__).read_text(),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return {"status": "unconfirmed", "reason": "container_unavailable"}
    if result.returncode:
        return {"status": "unconfirmed", "reason": "container_unavailable"}
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return {"status": "unconfirmed", "reason": "invalid_probe_response"}
    if not isinstance(payload, dict):
        return {"status": "unconfirmed", "reason": "invalid_probe_response"}
    return payload


def show(step: int, status: str, message: str) -> None:
    """Print one readable diagnostic step without dumping raw server responses."""
    print(f"[{status}] {step}. {message}")


def loopback_only(port: int) -> bool:
    """Confirm a local TCP listener is limited to loopback when ss is available."""
    if shutil.which("ss") is None:
        return False
    try:
        result = subprocess.run(
            ["ss", "-ltnH", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    addresses = [line.split()[3] for line in result.stdout.splitlines() if len(line.split()) >= 4]
    return bool(addresses) and all(
        value.startswith(("127.0.0.1:", "[::1]:")) for value in addresses
    )


def connection_advice(url: str, reason: str) -> None:
    """Explain observed connection failures and print manual actions only."""
    advice = {
        "dns": "The app cannot resolve the server name. Check the hostname and Docker host alias.",
        "refused": "Connection refused. Check the server's listening address and port.",
        "timeout": "Request timed out. Check routing, server load, and access rules.",
        "tls": "TLS verification failed. Check the protocol and trusted certificate.",
        "authentication": "Authentication rejected. Check credentials for this server.",
        "invalid_response": "Unexpected model API response. Check the URL and protocol.",
        "invalid_url": "Enter a valid HTTP/HTTPS URL in Settings > Local LLM.",
    }
    print("  " + advice.get(reason, "Check that the configured server is reachable from the app."))
    parsed = urlsplit(url)
    if parsed.hostname in {"127.0.0.1", "localhost"}:
        print("  Docker localhost is the app container; use host.docker.internal for this PC.")
    if parsed.hostname == "host.docker.internal" and parsed.scheme == "http":
        port = parsed.port or 80
        native = f"http://127.0.0.1:{port}{parsed.path}"
        host = probe_url(native)
        if host.get("status") == "reachable":
            print("  Host HTTP probe succeeded; this does not prove container access.")
            if loopback_only(port):
                print("  Confirmed: this PC's server only listens on loopback.")
                print("  See README > Ollama for the existing service's OLLAMA_HOST setting.")
    print("  Inspect the existing server: systemctl status ollama --no-pager; ollama list")
    print("  Diagnose the listener: ss -ltn 'sport = :11434'")
    print("  No services, models, or settings were changed.")


def diagnose(root: Path, web_url: str, *, client: httpx.Client | None = None) -> int:
    """Read effective app state first so stale dotenv values cannot select the wrong server."""
    base = valid_url(web_url)
    if base.endswith("/docreview-rag-agent"):
        base = base[: -len("/docreview-rag-agent")]
    api = f"{base}/docreview-rag-agent/api"
    owned_client = client is None
    active = client or httpx.Client(timeout=6, follow_redirects=False)
    try:
        try:
            release_response = active.get(f"{api}/release/")
            release_response.raise_for_status()
            release = release_response.json()
            environment = release.get("environment")
            if environment not in {"dev", "prod"}:
                show(
                    1,
                    "SKIP",
                    "The running API does not report its environment. Start the updated stack.",
                )
                return 2
            show(1, "PASS", f"Running mode: {environment} (reported by the API, not .env MODE).")
            health_response = active.get(f"{api}/health/")
            health_response.raise_for_status()
            if health_response.json().get("status") != "ok":
                show(2, "FAIL", "The API liveness response is not healthy.")
                return 1
            show(2, "PASS", "Web entry and API respond over the same HTTP address.")
            if environment == "prod":
                for step, message in [
                    (3, "Local connections"),
                    (4, "Model metadata"),
                    (5, "Local readiness"),
                ]:
                    show(
                        step,
                        "SKIP",
                        f"{message}: intentionally disabled in prod; no model requests sent.",
                    )
                return 0
            config_response = active.get(f"{api}/admin/local-llm/connection/")
            config_response.raise_for_status()
            config = config_response.json()
            if not isinstance(config, dict) or not isinstance(config.get("local", {}), dict):
                raise ValueError("invalid connection response")
            ready_response = active.get(f"{api}/ready/")
            ready_response.raise_for_status()
            ready = ready_response.json().get("review_engines", {}).get("local", {})
        except httpx.HTTPError as error:
            show(2, "FAIL", f"App HTTP request failed ({failure_kind(error)}).")
            print("  Run rag-dev up -d, then rag-dev logs app web. No model URL was guessed.")
            return 1
        except ValueError, AttributeError:
            show(
                2, "FAIL", "The API returned an unexpected response; check the running app version."
            )
            return 1
        source = config.get("source", "unknown")
        sources = {"saved", "environment", "dotenv", "default", "disabled", "invalid"}
        print(f"  Connection source: {source if source in sources else 'unknown'}")
        url = config.get("base_url")
        if not url or source in {"disabled", "invalid"}:
            show(3, "FAIL", "Local connection is disabled or its saved configuration is invalid.")
            print("  Open Settings > Local LLM and connect, or reset to the initial settings.")
            return 1
        local = config.get("local", {})
        reachable = local.get("enabled") is True or local.get("reason") == "no_answer_models"
        if not reachable:
            probe = container_probe(root, url, config.get("protocol", "auto"))
            if probe.get("status") == "disabled":
                show(3, "FAIL", "Mode changed to prod during diagnosis. Run the command again.")
                return 1
            if probe.get("status") != "reachable":
                incomplete = probe.get("status") == "unconfirmed"
                show(
                    3,
                    "SKIP" if incomplete else "FAIL",
                    f"Backend HTTP probe: {probe.get('reason', 'connection')}.",
                )
                connection_advice(url, str(probe.get("reason", "connection")))
                return 2 if incomplete else 1
            local = probe["local"]
        show(3, "PASS", "The backend reached the configured model server over HTTP.")
        models = local.get("models", [])
        selectable = [model for model in models if model.get("selectable")]
        show(
            4,
            "PASS" if selectable else "FAIL",
            f"Installed: {len(models)}; answer-capable: {len(selectable)}.",
        )
        for model in models:
            loaded = {
                True: "loaded",
                False: "not loaded (normal standby)",
                None: "load state not provided",
            }.get(model.get("loaded"))
            role = "answer" if model.get("selectable") else "not answer-capable"
            print(f"  {model.get('name', 'unknown')}: {role}; {loaded}")
        if not selectable:
            print("  Install an answer-capable model on the server. No models were downloaded.")
        if ready.get("enabled") is True:
            show(
                5,
                "PASS",
                "Local LLM is available in the browser; choose it below the conversation input.",
            )
        else:
            show(
                5,
                "FAIL",
                "No answer model is available in the app. Recheck after discovery refreshes.",
            )
        return 0 if selectable and ready.get("enabled") is True else 1
    finally:
        if owned_client:
            active.close()


def main() -> int:
    """Run normal diagnostics or the bounded internal container probe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--web-url", help="Web origin or DocReview page URL; defaults to configured APP_PORT."
    )
    parser.add_argument("--probe", help=argparse.SUPPRESS)
    parser.add_argument(
        "--protocol",
        default="auto",
        choices=["auto", "ollama", "openai_responses"],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe_url(args.probe, args.protocol)))
        return 0
    root = Path(__file__).resolve().parents[1]
    values = {**dotenv_values(root / ".env"), **os.environ}
    host = values.get("DOCREVIEW_LOCAL_HOST") or "127.0.0.1"
    port = values.get("APP_PORT") or "8000"
    try:
        return diagnose(root, args.web_url or f"http://{host}:{port}")
    except ValueError:
        show(1, "FAIL", "Invalid web URL. Use --web-url http://localhost:8000.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
