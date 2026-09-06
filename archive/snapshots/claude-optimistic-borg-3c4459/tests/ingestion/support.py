"""Shared pure helpers for ingestion API tests."""

import asyncio

import httpx


def client_returning(handler) -> httpx.AsyncClient:
    """Build a mock-transport client for one handler."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coroutine):
    """Run one asynchronous client operation to completion."""
    return asyncio.run(coroutine)
