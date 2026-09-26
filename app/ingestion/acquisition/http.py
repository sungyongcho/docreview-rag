"""Bounded, streamed HTTP acquisition without provider credentials in errors."""

import asyncio
from collections.abc import Mapping

import httpx

from app.ingestion.progress import ByteProgress


class AcquisitionHttpError(RuntimeError):
    """Carry safe transport details for a registry-specific error boundary."""

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        """Keep the request URL, query parameters and credentials out of failures."""
        super().__init__(reason)
        self.status = status


def declared_length(response: httpx.Response) -> int | None:
    """Return a decoded-byte total only for an uncompressed positive Content-Length."""
    if response.headers.get("content-encoding", "").strip().lower() not in ("", "identity"):
        return None
    try:
        value = int(response.headers.get("content-length", ""))
    except ValueError:
        return None
    return value if value > 0 else None


async def fetch_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: httpx.Timeout,
    max_bytes: int,
    attempts: int,
    backoff_seconds: float,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    on_progress: ByteProgress | None = None,
) -> bytes:
    """Retry transport failures, preserving HTTP failure and decoded-size boundaries."""
    for attempt in range(attempts):
        try:
            async with client.stream(
                "GET", url, headers=headers, params=params, timeout=timeout
            ) as response:
                if response.status_code != 200:
                    raise AcquisitionHttpError(
                        "unexpected http status", status=response.status_code
                    )
                total = declared_length(response)
                if on_progress is not None:
                    on_progress(0, total)
                chunks: list[bytes] = []
                held = 0
                async for chunk in response.aiter_bytes():
                    held += len(chunk)
                    if held > max_bytes:
                        raise AcquisitionHttpError(f"response exceeds {max_bytes} bytes")
                    chunks.append(chunk)
                    if on_progress is not None:
                        on_progress(held, total)
                return b"".join(chunks)
        except httpx.RequestError as error:
            failure = type(error).__name__
            if attempt + 1 < attempts:
                await asyncio.sleep(backoff_seconds * (attempt + 1))
    raise AcquisitionHttpError(f"request failed after {attempts} attempts ({failure})") from None
