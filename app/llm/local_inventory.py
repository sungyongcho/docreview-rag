"""Bounded, read-only discovery of a separately managed local model server."""

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import math
from time import monotonic
from typing import Any

import httpx

from app.llm.local_diagnostics import failure_kind
from app.llm.local_engine import resolve_local_protocol

CACHE_TTL_S = 10.0
PROBE_TIMEOUT_S = 2.0
CPU_MEASUREMENT_TTL_S = 15 * 60


@dataclass(frozen=True)
class LocalCpuPerformance:
    """Generation speed from a recent measured run on this server and model digest."""

    tokens_per_second: float
    measured_at: str


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
    cpu_performance: LocalCpuPerformance | None = None


@dataclass(frozen=True)
class LocalInventorySnapshot:
    """One immutable discovery result shared by readiness and request validation."""

    protocol: str
    models: tuple[LocalModelInfo, ...]
    checked_at: str
    reason: str | None = None
    failure_code: str | None = None

    @property
    def available_models(self) -> tuple[str, ...]:
        """Return only models that may be selected for an answer."""
        return tuple(model.name for model in self.models if model.selectable)

    def public_state(self) -> dict[str, Any]:
        """Serialize discovery with a default only when exactly one model is usable."""
        available = self.available_models
        metadata = asdict(self)
        metadata.pop("failure_code")
        return {
            **metadata,
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
        self._cpu_measurements: dict[tuple[str, str], tuple[float, LocalCpuPerformance]] = {}

    async def snapshot(self) -> LocalInventorySnapshot:
        """Coalesce concurrent readers and bound the entire refresh to two seconds."""
        async with self._lock:
            if self._cached is not None and monotonic() < self._expires_at:
                return self._cached
            try:
                async with asyncio.timeout(PROBE_TIMEOUT_S):
                    models = await self._fetch()
                reason = None if any(model.selectable for model in models) else "no_answer_models"
                failure_code = None
            except (httpx.HTTPError, httpx.InvalidURL, ValueError, TimeoutError) as error:
                models = ()
                reason = "unreachable"
                failure_code = failure_kind(error)
            self._cached = LocalInventorySnapshot(
                protocol=self.protocol,
                models=models,
                checked_at=datetime.now(UTC).isoformat(),
                reason=reason,
                failure_code=failure_code,
            )
            self._expires_at = monotonic() + CACHE_TTL_S
            return self._cached

    def model_digest(self, model_name: str) -> str | None:
        """Capture the discovered digest before a run can outlive its model tag."""
        return next((digest for name, digest in self._details if name == model_name), None)

    def record_cpu_performance(
        self,
        model_name: str,
        placement: dict[str, Any],
        model_calls: object,
        *,
        model_digest: str | None,
    ) -> None:
        """Retain valid generation timing only for the model actually measured on CPU."""
        names = {model_name, model_name + ":latest"}
        keys = [key for key in self._details if key[0] in names]
        for key in keys:
            self._cpu_measurements.pop(key, None)
        self._expires_at = 0.0
        if (
            self.protocol != "ollama"
            or not model_digest
            or placement.get("digest") != model_digest
            or placement.get("placement") != "cpu"
            or placement.get("model") not in names
            or not isinstance(model_calls, list)
        ):
            return
        tokens = duration_ms = 0.0
        for call in model_calls:
            if (
                not isinstance(call, dict)
                or call.get("provider") != "ollama"
                or call.get("model") not in names
            ):
                continue
            timings = call.get("local_timings")
            if not isinstance(timings, list):
                continue
            for timing in timings:
                if not isinstance(timing, dict):
                    continue
                count, duration = timing.get("eval_count"), timing.get("eval_duration_ms")
                if (
                    isinstance(count, bool)
                    or not isinstance(count, (int, float))
                    or isinstance(duration, bool)
                    or not isinstance(duration, (int, float))
                    or not math.isfinite(count)
                    or not math.isfinite(duration)
                    or count <= 0
                    or duration <= 0
                ):
                    continue
                tokens += count
                duration_ms += duration
        if duration_ms <= 0:
            return
        speed = tokens / duration_ms * 1000
        if not math.isfinite(speed) or speed <= 0:
            return
        measurement = LocalCpuPerformance(speed, datetime.now(UTC).isoformat())
        for key in keys:
            if key[1] == model_digest:
                self._cpu_measurements[key] = (monotonic(), measurement)

    def _cpu_performance(
        self, model: LocalModelInfo, loaded: dict[str, dict[str, Any]] | None
    ) -> LocalCpuPerformance | None:
        """Suppress old samples and require current evidence of CPU-only placement."""
        row = loaded.get(model.name) if loaded is not None else None
        if row is None or type(row.get("size_vram")) is not int or row["size_vram"] != 0:
            return None
        if type(row.get("size")) is not int or row["size"] <= 0:
            return None
        for key, (recorded_at, measurement) in self._cpu_measurements.items():
            if (
                key == (model.name, row.get("digest"))
                and key in self._details
                and monotonic() - recorded_at < CPU_MEASUREMENT_TTL_S
            ):
                return measurement
        return None

    async def placement(self, model_name: str) -> dict[str, Any]:
        """Read post-run Ollama placement without loading or changing a model."""
        if self.protocol != "ollama":
            return {"reason": "provider_does_not_report_placement"}
        headers = {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with asyncio.timeout(PROBE_TIMEOUT_S):
                async with httpx.AsyncClient(
                    timeout=PROBE_TIMEOUT_S, headers=headers, transport=self._transport
                ) as client:
                    response = await client.get(f"{self.base_url}/api/ps")
                    response.raise_for_status()
                    rows = _models(response.json(), "models", "name")
            row = next(
                (
                    item
                    for item in rows
                    if item["name"] == model_name or item["name"] == model_name + ":latest"
                ),
                None,
            )
            if row is None:
                return {"reason": "model_not_loaded"}
            size, vram = row.get("size"), row.get("size_vram")
            if type(size) is not int or size <= 0 or type(vram) is not int or vram < 0:
                return {"reason": "ollama_memory_fields_unavailable"}
            return {
                "source": "ollama_api_ps",
                "model": row["name"],
                "digest": _text(row.get("digest")),
                "size_bytes": size,
                "vram_bytes": vram,
                "placement": "cpu" if vram == 0 else "gpu" if vram >= size else "mixed",
                "checked_at": datetime.now(UTC).isoformat(),
                "reason": None,
            }
        except httpx.HTTPError, ValueError, TimeoutError:
            return {"reason": "ollama_placement_unavailable"}

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
            current_keys = {(item["name"], _text(item.get("digest")) or "") for item in entries}
            self._details = {
                key: value for key, value in self._details.items() if key in current_keys
            }
            self._cpu_measurements = {
                key: value for key, value in self._cpu_measurements.items() if key in current_keys
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
                replace(
                    model,
                    loaded=model.name in loaded if loaded is not None else None,
                    cpu_performance=self._cpu_performance(model, loaded),
                )
                for model in models
            )

    async def _loaded(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]] | None:
        """Treat optional load-state failures as unknown, not as an empty running list."""
        try:
            response = await client.get(f"{self.base_url}/api/ps")
            response.raise_for_status()
            return {item["name"]: item for item in _models(response.json(), "models", "name")}
        except httpx.HTTPError, ValueError:
            return None

    async def _describe(self, client: httpx.AsyncClient, item: dict[str, Any]) -> LocalModelInfo:
        """Only offer Ollama models whose declared capabilities include completion."""
        key = (item["name"], _text(item.get("digest")) or "")
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
