"""Validate local PROD restoration boundaries without modifying real services in unit tests."""

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.stack import cli, prod


@pytest.fixture
def environment(tmp_path, monkeypatch):
    """Inject transport and a tiny public source contract; leave ownership checks observable."""
    root = tmp_path / "checkout"
    root.mkdir()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "checksums.json").write_text("{}")
    (bundle / "database.public.dump").write_bytes(b"public fixture")
    (bundle / "database.private.dump").write_bytes(b"must not be read")
    receipt = tmp_path / "receipt.json"
    manifest = {"documents": [{"document_id": "public"}], "artifacts": []}
    database = Mock()
    database.isolated.return_value = True
    database.report.side_effect = [
        {
            "documents": None,
            "chunks": 0,
            "embeddings": 0,
            "snapshots": 0,
            "runs": 0,
            "traces": 0,
            "operator_jobs": 0,
        },
        {"documents": ["public"], "chunks": 1, "matching_embeddings": 1},
    ]
    database.sql.return_value = "t"
    monkeypatch.setattr(cli, "require_running_mode", Mock())
    monkeypatch.setattr(prod, "LocalDatabase", lambda _: database)
    monkeypatch.setattr(prod, "receipt_path", lambda *_: receipt)
    monkeypatch.setattr(prod, "validate_artifacts", Mock(return_value=manifest))
    monkeypatch.setattr(prod, "validate_database", Mock())
    monkeypatch.setattr(prod, "validate_restored_files", Mock())
    monkeypatch.setattr(prod, "extract_artifacts", Mock())
    monkeypatch.setattr(prod, "wait_search_ready", Mock(return_value={"status": "ready"}))

    def record(root, name, **values):
        """Persist the real state transition shape in the disposable test directory."""
        receipt.write_text(json.dumps(values))

    monkeypatch.setattr(prod, "write_receipt", record)
    return root, bundle, receipt, database


def test_check_is_read_only(environment, monkeypatch):
    """A preflight cannot create directories, write receipts or mutate Docker."""
    root, bundle, receipt, database = environment
    forbidden = Mock(side_effect=AssertionError("Read-only command must not mutate"))
    monkeypatch.setattr(prod, "ensure_storage", forbidden)
    monkeypatch.setattr(prod, "write_receipt", forbidden)
    assert prod.prepare(root, artifacts=bundle, check=True) == 0
    assert not receipt.exists()
    assert not (root / "data").exists()
    database.run.assert_not_called()


def test_restore_only_uses_public_dump_and_records_actual_readiness(environment):
    """Restore targets isolated empty storage and never imports the adjacent private dump."""
    root, bundle, receipt, database = environment
    assert prod.prepare(root, artifacts=bundle) == 0
    calls = database.run.call_args_list
    restore = next(call for call in calls if "pg_restore" in call.args)
    assert restore.kwargs["input_file"] == bundle / "database.public.dump"
    assert {"--single-transaction", "--disable-triggers", "--data-only"} <= set(restore.args)
    assert calls[0].args == ("stop", "app")
    database.validate_references.assert_called_once()
    assert json.loads(receipt.read_text())["status"] == "succeeded"


def test_wrong_running_mode_stops_before_any_preparation(environment, monkeypatch):
    """A DEV runtime can never receive a local PROD restore."""
    root, bundle, _, database = environment
    monkeypatch.setattr(cli, "require_running_mode", Mock(side_effect=ValueError("Not PROD")))
    with pytest.raises(ValueError, match="Not PROD"):
        prod.prepare(root, artifacts=bundle)
    database.run.assert_not_called()


def test_nonempty_sources_are_preserved_without_stopping_api(environment):
    """Unmanaged source files are a conflict, never a reason to overwrite a target."""
    root, bundle, _, database = environment
    source = root / "data/local-prod/corpus/user.txt"
    source.parent.mkdir(parents=True)
    source.write_text("preserve")
    with pytest.raises(ValueError, match="not empty"):
        prod.prepare(root, artifacts=bundle)
    assert source.read_text() == "preserve"
    database.run.assert_not_called()


def test_failed_restore_is_recorded_and_not_retried(environment):
    """Partial preparation retains its failure and cannot be promoted or silently replayed."""
    root, bundle, receipt, database = environment

    def run(*args, **kwargs):
        """Fail exactly at the data restoration boundary."""
        if "pg_restore" in args:
            raise RuntimeError("restore failed")
        return ""

    database.run.side_effect = run
    with pytest.raises(RuntimeError, match="restore failed"):
        prod.prepare(root, artifacts=bundle)
    assert json.loads(receipt.read_text())["status"] == "failed"
    count = database.run.call_count
    prod.validate_database.side_effect = ValueError("Restored documents are incomplete")
    with pytest.raises(ValueError, match="Incomplete"):
        prod.prepare(root, artifacts=bundle)
    assert database.run.call_count == count
    prod.wait_search_ready.assert_not_called()


def test_verified_repeat_does_not_restore_or_erase_new_history(environment):
    """Revalidation preserves later user activity and invokes no restore commands."""
    root, bundle, _, database = environment
    assert prod.prepare(root, artifacts=bundle) == 0
    database.report.side_effect = None
    database.report.return_value = {"runs": 5, "traces": 10}
    database.run.reset_mock()
    assert prod.prepare(root, artifacts=bundle) == 0
    database.run.assert_not_called()
    assert prod.validate_database.call_args.kwargs == {"allow_runtime_history": True}


def test_storage_never_follows_foreign_symlinks(tmp_path):
    """A local mount cannot redirect restoration into another user's directory."""
    root = tmp_path / "checkout"
    root.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (root / "data").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        prod.ensure_storage(root)
    assert not list(foreign.iterdir())


def test_bundle_selection_is_explicit_or_unambiguous(tmp_path, monkeypatch):
    """Neither a missing bundle nor multiple saved bundles can trigger guessed data loading."""
    monkeypatch.delenv("DOCREVIEW_PROD_ARTIFACT_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / "checkout"
    root.mkdir()
    with pytest.raises(ValueError, match="Specify"):
        prod.artifact_directory(root, None)
    cache = tmp_path / ".local/share/docreview/prod-artifacts"
    first = cache / "first"
    first.mkdir(parents=True)
    (first / "checksums.json").write_text("{}")
    assert prod.artifact_directory(root, None) == first
    second = cache / "second"
    second.mkdir()
    (second / "checksums.json").write_text("{}")
    with pytest.raises(ValueError, match="Specify"):
        prod.artifact_directory(root, None)
    assert prod.artifact_directory(root, second) == second


def test_ready_start_validates_bundle_before_starting(environment, monkeypatch):
    """Prepared startup cannot create an empty stack after an invalid bundle preflight."""
    root, bundle, _, _ = environment
    from scripts.stack import quickstart

    start = Mock()
    monkeypatch.setattr(quickstart, "quickstart", start)
    monkeypatch.setattr(
        "deploy.gcp.verify_artifacts.validate_artifacts",
        Mock(side_effect=ValueError("checksum mismatch")),
    )
    assert (
        cli.main(["prod", "start", "--local", "--ready", "--artifacts", str(bundle)], root=root)
        == 2
    )
    start.assert_not_called()


def test_ready_start_connects_verified_startup_and_preparation(environment, monkeypatch):
    """The public ready-start command validates, starts PROD, then prepares the chosen bundle."""
    from scripts.stack import quickstart

    root, bundle, _, _ = environment
    order = []
    monkeypatch.setattr(
        "deploy.gcp.verify_artifacts.validate_artifacts", lambda _: order.append("validate")
    )
    start = Mock(side_effect=lambda *a, **k: order.append("start") or 0)
    prepare = Mock(side_effect=lambda *a, **k: order.append("prepare") or 0)
    monkeypatch.setattr(quickstart, "quickstart", start)
    monkeypatch.setattr(prod, "prepare", prepare)
    assert (
        cli.main(["prod", "start", "--local", "--ready", "--artifacts", str(bundle)], root=root)
        == 0
    )
    assert order == ["validate", "start", "prepare"]
    start.assert_called_once_with(root, mode="prod", timeout=180)
    prepare.assert_called_once_with(root, artifacts=bundle, check=False)


@pytest.mark.parametrize("action", ["prepare", "recreate"])
def test_dev_schema_mutation_cannot_target_running_prod(environment, monkeypatch, action):
    """Mode-specific schema commands cannot reach the other mode through a shared host port."""
    root, _, _, database = environment
    database.volume.return_value = f"{root.name}_prod_pg_data"
    invoke = Mock()
    monkeypatch.setattr(cli, "module", invoke)
    assert cli.main(["dev", "schema", action], root=root) == 2
    invoke.assert_not_called()


def test_complete_data_can_reconcile_a_readiness_failure_without_restoring(environment):
    """Completed, revalidated data may finish its receipt without importing anything again."""
    root, bundle, receipt, database = environment
    assert prod.prepare(root, artifacts=bundle) == 0
    values = json.loads(receipt.read_text()) | {"status": "failed", "error": "ReadinessError"}
    receipt.write_text(json.dumps(values))
    database.report.side_effect = None
    database.report.return_value = {"chunks": 1, "matching_embeddings": 1}
    database.run.reset_mock()
    before = receipt.read_bytes()
    assert prod.prepare(root, artifacts=bundle, check=True) == 0
    assert receipt.read_bytes() == before
    assert prod.prepare(root, artifacts=bundle) == 0
    database.run.assert_not_called()
    assert json.loads(receipt.read_text())["reconciled"] is True


def test_readiness_wait_handles_transient_non_json_proxy_response(tmp_path, monkeypatch):
    """A proxy's startup response cannot turn a completed restore into an immediate failure."""
    import io
    from urllib.error import HTTPError

    class Response(io.BytesIO):
        """Expose only the HTTP metadata used by the readiness reader."""

        status = 200
        headers = {"Content-Type": "application/json"}

    failure = HTTPError(
        "http://local/ready",
        502,
        "Bad Gateway",
        {"Content-Type": "text/plain"},
        io.BytesIO(b"Bad Gateway"),
    )
    opener = Mock()
    opener.open.side_effect = [failure, Response(b'{"environment":"prod","status":"ready"}')]
    monkeypatch.setattr(prod, "build_opener", lambda *_: opener)
    monkeypatch.setattr(prod.time, "sleep", lambda _: None)
    assert prod.wait_search_ready(tmp_path, timeout=1)["status"] == "ready"
    assert opener.open.call_count == 2


@pytest.mark.live_postgres
def test_prepared_local_prod_has_verified_sources_vectors_and_foreign_keys():
    """Read the explicitly selected local PROD volume; never create, clear or modify its data."""
    from tests.live_postgres import live_postgres_unavailable

    if os.environ.get("DOCREVIEW_LOCAL_PROD_ACCEPTANCE") != "1":
        live_postgres_unavailable("Enable explicit read-only local PROD acceptance")
    root = Path(__file__).resolve().parents[3]
    database = prod.LocalDatabase(root)
    assert database.isolated(), "The live acceptance target must be the dedicated local PROD volume"
    bundle = prod.artifact_directory(root, None)
    manifest = prod.validate_artifacts(bundle)
    report = database.report()
    prod.validate_database(manifest, report, allow_runtime_history=True)
    prod.validate_restored_files(bundle, prod.storage(root), manifest)
    database.validate_references()
    counts = json.loads(
        database.sql(
            "SELECT json_build_object('bm25_documents', (SELECT sum(n) FROM bm25_corpus_stats), "
            "'lengths', (SELECT count(*) FROM chunk_lengths), "
            "'chunks', (SELECT count(*) FROM chunks))"
        )
    )
    assert counts["bm25_documents"] == counts["lengths"] == counts["chunks"] == 10586
