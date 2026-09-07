"""Reproducible public/admin and local-operator client contracts."""

import json
from pathlib import Path
import sys

from scripts.export_api_schema import export_operator_schema, export_schema, main


def test_committed_contracts_match_the_real_api_factories():
    """Keep the two API surfaces separate and their generated inputs reproducible."""
    assert export_schema() == Path("schemas/api.openapi.json").read_text()
    operator = export_operator_schema()
    assert operator == Path("schemas/operator.openapi.json").read_text()
    assert "/commands" in json.loads(operator)["paths"]
    assert "/commands" not in json.loads(export_schema())["paths"]
    assert "schema-export-only" not in operator


def test_operator_cli_writes_and_checks_the_requested_output(tmp_path, monkeypatch):
    """Honor an explicit output for the operator option without changing the public default."""
    output = tmp_path / "operator.json"
    arguments = ["export_api_schema", "--operator", "--output", str(output)]
    monkeypatch.setattr(sys, "argv", arguments)
    main()
    assert json.loads(output.read_text())["components"]["schemas"]["CommandResource"]
    monkeypatch.setattr(sys, "argv", [*arguments, "--check"])
    main()
