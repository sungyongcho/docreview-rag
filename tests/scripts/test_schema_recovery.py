"""Isolated recovery creation preserves the source checkout and chooses independent targets."""

import subprocess

from dotenv import dotenv_values
import pytest

from scripts.schema_recovery import create_recovery, recovery_environment, wait_recovery


@pytest.fixture
def source(tmp_path):
    """Create a disposable committed repository with private untracked configuration."""
    root = tmp_path / "source"
    root.mkdir()
    (root / "tracked.txt").write_text("committed")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=root,
        check=True,
    )
    (root / ".env").write_text(
        "DB_PORT=5432\nAPP_PORT=8000\nDATABASE_URL=private-original\nOPENAI_API_KEY_LOCAL=private-sentinel\n"
    )
    (root / "tracked.txt").write_text("uncommitted edit")
    (root / "corpus.txt").write_text("private corpus")
    return root


def test_new_target_preserves_source_and_uses_distinct_ports(source, monkeypatch, capsys):
    """Copy committed source plus private config without reusing original services or data."""
    original = (source / ".env").read_bytes()
    target = create_recovery(source, source.parent)
    assert (source / ".env").read_bytes() == original
    assert (source / "tracked.txt").read_text() == "uncommitted edit"
    assert (source / "corpus.txt").read_text() == "private corpus"
    assert (target / "tracked.txt").read_text() == "committed"
    assert not (target / "corpus.txt").exists()
    values = dotenv_values(target / ".env")
    assert "DATABASE_URL" not in values
    assert values["OPENAI_API_KEY_LOCAL"] == "private-sentinel"
    assert len({values[key] for key in ("DB_PORT", "APP_PORT", "DOCREVIEW_OPERATOR_PORT")}) == 3
    assert (target / ".env").stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv("DATABASE_URL", "external")
    monkeypatch.setenv("APP_PORT", "8000")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", source.name)
    environment = recovery_environment(target)
    assert "DATABASE_URL" not in environment and "COMPOSE_PROJECT_NAME" not in environment
    assert environment["APP_PORT"] == values["APP_PORT"]
    assert environment["UV_PROJECT_ENVIRONMENT"] == str(target / ".venv")
    assert "private-sentinel" not in capsys.readouterr().out


def test_recovery_cannot_be_created_inside_source(source):
    """Refuse any target parent that could alter the user's original checkout."""
    with pytest.raises(ValueError, match="outside"):
        create_recovery(source, source)


def test_unknown_readiness_never_claims_success(monkeypatch):
    """A server that was not verified remains unresolved."""
    import scripts.schema_recovery as recovery

    monkeypatch.setattr(recovery.time, "monotonic", iter([0, 181]).__next__)
    with pytest.raises(RuntimeError, match="unconfirmed"):
        wait_recovery("http://127.0.0.1:1")
