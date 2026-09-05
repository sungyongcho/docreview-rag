"""Bounded, read-only discovery of a separately managed local model server."""

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import httpx

from app.llm.local_engine import resolve_local_protocol

CACHE_TTL_S = 10.0
PROBE_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class LocalModelInfo:
    """Public model metadata, excluding server addresses and credentials."""

    name: str
    selectable: bool
    size_bytes: int | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    capabilities: tuple[str, ...] | None = None
    loaded: bool | None = None


@dataclass(frozen=True)
class LocalInventorySnapshot:
    """One immutable discovery result shared by readiness and request validation."""

    protocol: str
    models: tuple[LocalModelInfo, ...]
    checked_at: str
    reason: str | None = None

    @property
    def available_models(self) -> tuple[str, ...]:
        """Return only models that may be selected for an answer."""
        return tuple(model.name for model in self.models if model.selectable)

    def public_state(self) -> dict[str, Any]:
        """Serialize discovery with a default only when exactly one model is usable."""
        available = self.available_models
        return {
            **asdict(self),
            "enabled": bool(available) and self.reason is None,
            "model": available[0] if len(available) == 1 else None,
        }


def _models(payload: object, key: str, name_key: str) -> list[dict[str, Any]]:
    """Validate the inventory envelope before using untrusted model identifiers."""
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ValueError("invalid model inventory")
    result = []
    for item in payload[key]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get(name_key), str)
            or not item[name_key].strip()
        ):
            raise ValueError("invalid model entry")
        result.append(item)
    return result


def _text(value: object) -> str | None:
    """Keep optional metadata only when the server supplied nonblank text."""
    return value if isinstance(value, str) and value.strip() else None


class LocalModelInventory:
    """Share short-lived probes and digest-keyed metadata without loading models."""

    def __init__(
        self,
        *,
        base_url: str,
        protocol: str = "auto",
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Keep connection settings private to the server and defer all HTTP work."""
        self.base_url = base_url.rstrip("/")
        self.protocol = resolve_local_protocol(base_url, protocol)
        self.api_key = api_key
        self._transport = transport
        self._lock = asyncio.Lock()
        self._cached: LocalInventorySnapshot | None = None
        self._expires_at = 0.0
        self._details: dict[tuple[str, str], LocalModelInfo] = {}

    async def snapshot(self) -> LocalInventorySnapshot:
        """Coalesce concurrent readers and bound the entire refresh to two seconds."""
        async with self._lock:
            if self._cached is not None and monotonic() < self._expires_at:
                return self._cached
            try:
                async with asyncio.timeout(PROBE_TIMEOUT_S):
                    models = await self._fetch()
                reason = None if any(model.selectable for model in models) else "no_answer_models"
            except httpx.HTTPError, httpx.InvalidURL, ValueError, TimeoutError:
                models = ()
                reason = "unreachable"
            self._cached = LocalInventorySnapshot(
                protocol=self.protocol,
                models=models,
                checked_at=datetime.now(UTC).isoformat(),
                reason=reason,
            )
            self._expires_at = monotonic() + CACHE_TTL_S
            return self._cached

    async def _fetch(self) -> tuple[LocalModelInfo, ...]:
        """Fetch native Ollama metadata or the existing OpenAI-compatible inventory."""
        headers = {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT_S, headers=headers, transport=self._transport
        ) as client:
            if self.protocol == "openai_responses":
                root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
                response = await client.get(f"{root}/v1/models")
                response.raise_for_status()
                return tuple(
                    LocalModelInfo(name=item["id"], selectable=True)
                    for item in _models(response.json(), "data", "id")
                )
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            entries = _models(response.json(), "models", "name")
            current_keys = {(item["name"], str(item.get("digest", ""))) for item in entries}
            self._details = {
                key: value for key, value in self._details.items() if key in current_keys
            }
            semaphore = asyncio.Semaphore(4)

            async def describe(item: dict[str, Any]) -> LocalModelInfo:
                """Limit concurrent detail requests while reusing unchanged metadata."""
                async with semaphore:
                    return await self._describe(client, item)

            loaded, models = await asyncio.gather(
                self._loaded(client), asyncio.gather(*(describe(item) for item in entries))
            )
            return tuple(
                replace(model, loaded=model.name in loaded if loaded is not None else None)
                for model in models
            )

    async def _loaded(self, client: httpx.AsyncClient) -> set[str] | None:
        """Treat optional load-state failures as unknown, not as an empty running list."""
        try:
            response = await client.get(f"{self.base_url}/api/ps")
            response.raise_for_status()
            return {item["name"] for item in _models(response.json(), "models", "name")}
        except httpx.HTTPError, ValueError:
            return None

    async def _describe(self, client: httpx.AsyncClient, item: dict[str, Any]) -> LocalModelInfo:
        """Only offer Ollama models whose declared capabilities include completion."""
        key = (item["name"], str(item.get("digest", "")))
        if key[1] and key in self._details:
            return self._details[key]
        details = item.get("details", {})
        if not isinstance(details, dict):
            details = {}
        capabilities = None
        try:
            response = await client.post(f"{self.base_url}/api/show", json={"model": item["name"]})
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("invalid model details")
            supplied = body.get("capabilities")
            if isinstance(supplied, list) and all(isinstance(value, str) for value in supplied):
                capabilities = tuple(supplied)
            if isinstance(body.get("details"), dict):
                details = body["details"]
        except httpx.HTTPError, ValueError:
            # Tags still provide display metadata; unverified models remain unselectable.
            capabilities = None
        size = item.get("size")
        model = LocalModelInfo(
            name=item["name"],
            selectable=capabilities is not None and "completion" in capabilities,
            size_bytes=size if type(size) is int and size >= 0 else None,
            family=_text(details.get("family")),
            parameter_size=_text(details.get("parameter_size")),
            quantization_level=_text(details.get("quantization_level")),
            capabilities=capabilities,
        )
        if key[1] and capabilities is not None:
            self._details[key] = model
        return model
