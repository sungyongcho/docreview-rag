"""Test stand-ins with one home, grouped by the dependency they replace.

- :mod:`tests.support.models`: chat models, tool-calling providers, OpenAI clients
  and endpoints, and embedding models;
- :mod:`tests.support.transport`: MCP servers to connect to and an MCP client, with
  the server processes :mod:`tests.support.controlled_filings`,
  :mod:`tests.support.cell_filings` and :mod:`tests.support.stdio_relay`;
- :mod:`tests.support.database`: database sessions, session factories and engines;
- :mod:`tests.support.settings`: settings construction for configuration tests.

A test that needs one of these imports it from here instead of defining its own, so
the same dependency is always replaced the same way.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
