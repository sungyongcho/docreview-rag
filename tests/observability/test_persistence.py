"""Secret-safe record mapping and transaction-neutral run persistence."""

import asyncio

import pytest

from app.db.models import Run, Trace
from app.observability.persistence import (
    REDACTED,
    persist_run_report,
    redact_sensitive_text,
    report_to_records,
)
from tests.observability.support import run_report, step_trace


def test_persistence_mapping_preserves_provenance_and_redacts_secrets():
    """Preserve run provenance while redacting secrets on the way to storage."""
    secret = "sk-test-secret-123456"
    report = run_report(
        status="schema_rejected",
        system_prompt=f"Use evidence. API_KEY={secret}",
        report={"reason": f"provider rejected Bearer {secret}"},
        steps=[
            step_trace(
                api_url=f"https://example.test/responses?api_key={secret}",
                llm_output=f'{{"raw":"{secret}","kept":"evidence"}}',
                error=f"Authorization: Bearer {secret}",
            )
        ],
    )

    run, traces = report_to_records(report, secret_values=[secret])

    trace = traces[0]
    assert run.run_id == report.run_id
    assert run.status == "schema_rejected"
    assert run.node_path == ["retrieve", "grade"]
    assert "Use evidence." in run.system_prompt
    assert "evidence" in trace.llm_output
    assert secret not in run.system_prompt
    assert secret not in repr(run.report)
    assert secret not in trace.api_url
    assert secret not in trace.llm_output
    assert secret not in trace.error
    assert REDACTED in run.system_prompt
    assert REDACTED in trace.llm_output


def test_redaction_covers_quoted_assignments_and_rejects_key_collisions():
    """Redact quoted secret assignments and reject colliding redaction keys."""

    assert redact_sensitive_text('password="alpha beta"') == "password=[REDACTED]"
    assert redact_sensitive_text("secret='alpha beta'") == "secret=[REDACTED]"
    assert (
        redact_sensitive_text(
            "pair abcdef123 abcdef",
            secret_values=["abcdef", "abcdef123"],
        )
        == "pair [REDACTED] [REDACTED]"
    )

    collision = run_report(report={"api_key=foo": "first", "api_key=bar": "second"})
    with pytest.raises(ValueError, match="duplicate JSON key"):
        report_to_records(collision)


def test_redaction_reaches_json_credentials_and_stops_at_the_query_boundary():
    """Redact secrets written as JSON and keep the rest of a URL readable."""

    assert redact_sensitive_text('{"access_token": "abc123def"}') == '{"access_token": [REDACTED]}'
    assert redact_sensitive_text("{'password': 'hunter2'}") == "{'password': [REDACTED]}"
    assert (
        redact_sensitive_text('headers={"Authorization": "Basic YWxpY2U6c2VjcmV0"}')
        == 'headers={"Authorization": [REDACTED]}'
    )
    # An authorization header is one value, not a scheme plus a separate secret.
    assert redact_sensitive_text("Authorization: Bearer abc.def-ghi") == "Authorization: [REDACTED]"
    assert (
        redact_sensitive_text("https://api.test/v1/responses?api_key=sk-abcdefgh12&model=mini")
        == "https://api.test/v1/responses?api_key=[REDACTED]&model=mini"
    )


def test_credential_keys_in_a_report_have_their_values_replaced_wholesale():
    """Replace whatever a credential-shaped report key holds, not just matching text."""
    report = run_report(
        report={
            "openai_api_key": "abc123def",
            "nested": {"password": "hunter2", "label": "SUPPORTED"},
        }
    )

    run, _ = report_to_records(report)

    assert run.report == {
        "openai_api_key": REDACTED,
        "nested": {"password": REDACTED, "label": "SUPPORTED"},
    }


def test_equal_length_secrets_redact_in_one_stable_pass():
    """Replace every explicit secret in one pass, independent of the order supplied."""
    # "REDACT" occurs inside the replacement text, so a second sequential replacement
    # would rewrite what the first one produced.
    secrets = ["ABCDEF", "REDACT"]

    assert redact_sensitive_text("ABCDEF", secret_values=secrets) == REDACTED
    assert redact_sensitive_text("ABCDEF", secret_values=list(reversed(secrets))) == REDACTED


def test_persistence_flushes_without_committing_or_live_services():
    """Flush a run report without committing or reaching any live service."""

    class RecordingSession:
        """Record what persistence adds and flushes, without a database."""

        def __init__(self):
            self.added = []
            self.added_many = []
            self.flushed = False

        def add(self, value):
            self.added.append(value)

        def add_all(self, values):
            self.added_many.extend(values)

        async def flush(self):
            self.flushed = True

    session = RecordingSession()
    persisted = asyncio.run(persist_run_report(session, run_report()))

    assert persisted is session.added[0]
    assert isinstance(persisted, Run)
    assert len(session.added_many) == 1
    assert isinstance(session.added_many[0], Trace)
    assert session.flushed
