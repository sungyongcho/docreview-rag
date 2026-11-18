"""The filings MCP server entry point stays a development tool."""

import asyncio
from types import SimpleNamespace

import pytest

from app.mcp import filings_server


def test_production_mode_is_refused_before_serving(monkeypatch, capsys):
    """MODE=prod exits with code 2 on stderr and never starts the server."""

    async def serve(registry):
        raise AssertionError("the server must not start in production mode")

    monkeypatch.setattr(filings_server, "get_settings", lambda: SimpleNamespace(environment="prod"))
    monkeypatch.setattr(filings_server, "serve", serve)

    with pytest.raises(SystemExit) as stopped:
        asyncio.run(filings_server.main())

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refusing MODE=prod" in captured.err
