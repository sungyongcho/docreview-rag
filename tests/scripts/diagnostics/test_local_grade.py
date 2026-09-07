"""Pure helpers of the local grade benchmark; no model is loaded here."""

import os

import pytest

from scripts.diagnostics.local_grade import (
    classify_placement,
    grade_prompt,
    hits_from_records,
    main,
    render_markdown,
    summarize_run,
)


def _record(chunk_id: int, body: str) -> dict:
    """Build one /retrieve result row."""
    return {
        "chunk_id": chunk_id,
        "doc_id": "NVDA-FY2024",
        "item": "7",
        "section_title": "Management's Discussion and Analysis",
        "kind": "text",
        "citation": "NVDA FY2024 · Item 7",
        "start_char": 0,
        "end_char": len(body),
        "source_sha256": "0" * 64,
        "body": body,
        "context_header": "NVDA FY2024 · Item 7",
        "score": 0.9,
    }


def test_retrieve_rows_become_hits_and_the_workflow_grade_prompt():
    """Rows lacking index_text still validate, and the prompt carries every chunk id."""
    hits = hits_from_records([_record(1, "Data Center revenue was up."), _record(2, "Weather.")])
    assert [hit.chunk_id for hit in hits] == [1, 2]
    assert hits[0].index_text.endswith("Data Center revenue was up.")
    prompt = grade_prompt("What drove growth?", hits, max_context_chars=12_000)
    assert '"chunk_id":1' in prompt.user and '"chunk_id":2' in prompt.user
    assert "at most 20 words" in prompt.user


def test_summary_reads_timings_thinking_and_json_validity():
    """Token rates come from Ollama's nanosecond timings; hidden reasoning is measured."""
    response = {
        "message": {
            "content": '{"grades":[{"chunk_id":1,"relevant":true,"reason":"Direct."}]}',
            "thinking": "x" * 40,
        },
        "prompt_eval_count": 2000,
        "prompt_eval_duration": 20_000_000_000,
        "eval_count": 50,
        "eval_duration": 5_000_000_000,
        "load_duration": 500_000_000,
        "done_reason": "stop",
    }
    run = summarize_run(
        schema="bounded",
        think=True,
        num_predict=300,
        prompt_chars=9_000,
        response=response,
        total_s=26.0,
    )
    assert (run.prompt_eval_tps, run.eval_tps, run.load_ms) == (100.0, 10.0, 500.0)
    assert run.thinking_chars == 40
    assert run.json_valid is True
    assert (run.grades, run.max_reason_chars) == (1, 7)
    empty = summarize_run(
        schema="current",
        think=True,
        num_predict=600,
        prompt_chars=9_000,
        response={
            "message": {"content": "", "thinking": "y" * 900},
            "eval_count": 600,
            "eval_duration": 60_000_000_000,
            "done_reason": "length",
        },
        total_s=60.0,
    )
    assert empty.json_valid is False
    assert empty.content_chars == 0
    table = render_markdown([run, empty])
    assert table.splitlines()[0].startswith("| schema |")
    assert "| current | True | 600 |" in table


def test_placement_mirrors_the_inventory_rule():
    """Zero VRAM means CPU, full VRAM means GPU, partial means mixed."""
    assert classify_placement(9_000, 0) == "cpu"
    assert classify_placement(9_000, 9_000) == "gpu"
    assert classify_placement(9_000, 4_000) == "mixed"
    assert classify_placement(None, None) == "unknown"


def test_main_refuses_in_production_mode(monkeypatch, capsys):
    """Production mode never loads or runs a local model."""
    monkeypatch.setenv("MODE", "prod")
    monkeypatch.setattr("sys.argv", ["benchmark", "--evidence-file", os.devnull])
    assert main() == 2
    assert "production" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        monkeypatch.setenv("MODE", "dev")
        monkeypatch.setattr("sys.argv", ["benchmark"])
        main()
