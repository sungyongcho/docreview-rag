"""Benchmark the grade call of a local Ollama model and report its real cost.

Unlike ``scripts/diagnostics/ollama.py``, this script loads the model and generates: it
builds the same grade prompt the workflow sends for one question, calls ``/api/chat``
with the structured-output schema, and records prompt tokens, prompt-evaluation and
generation speed, whether hidden reasoning consumed the output allowance, and whether
the JSON validated. Run it against an isolated stack; it is refused in production mode.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
import sys
import time
from typing import Any
from uuid import uuid4

import httpx
import tiktoken

from app.llm.estimate import estimate_prompt_tokens
from app.llm.schemas import NonBlank, Prompt, RelevanceJudgment, StrictSchema
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.workflow.prompts import build_grade_prompt
from app.workflow.types import DEFAULT_SYSTEM_PROMPT, WorkflowState

DEFAULT_QUERY = "What drove NVIDIA data center revenue growth?"
KOREAN_SAMPLE = (
    "당사는 메모리 반도체와 시스템 반도체를 생산하며, 데이터센터 수요 증가에 따라 "
    "고대역폭 메모리 매출이 전년 대비 크게 증가하였습니다. 재고자산은 감소하였습니다."
)


class _UnboundedChunkRelevance(StrictSchema):
    """The grade schema before rationale length was bounded (kept for comparison)."""

    chunk_id: int
    relevant: bool
    reason: NonBlank


class _UnboundedJudgment(StrictSchema):
    """Container matching the pre-change grade schema."""

    grades: tuple[_UnboundedChunkRelevance, ...]


SCHEMAS: dict[str, type[StrictSchema]] = {
    "bounded": RelevanceJudgment,
    "current": _UnboundedJudgment,
}


@dataclass(frozen=True, slots=True)
class GradeRun:
    """One measured grade call."""

    schema: str
    think: bool
    num_predict: int
    prompt_chars: int
    prompt_eval_count: int | None
    prompt_eval_tps: float | None
    eval_count: int | None
    eval_tps: float | None
    load_ms: float | None
    total_s: float
    done_reason: str | None
    thinking_chars: int
    content_chars: int
    json_valid: bool
    grades: int | None
    max_reason_chars: int | None
    error: str | None


def hits_from_records(records: list[dict[str, Any]]) -> list[ChunkHit]:
    """Turn ``/retrieve`` result rows into the chunk hits the grade prompt serializes."""
    hits = []
    for row in records:
        payload = {key: row[key] for key in ChunkHit.model_fields if key in row}
        payload.setdefault(
            "index_text", f"{row.get('context_header', '')}\n\n{row['body']}".strip()
        )
        hits.append(ChunkHit.model_validate(payload))
    return hits


def grade_prompt(query: str, hits: list[ChunkHit], *, max_context_chars: int) -> Prompt:
    """Build the workflow's grade prompt for ``hits`` exactly as the runner would."""
    state = WorkflowState(
        run_id=f"run-{uuid4().hex}",
        query=query,
        k=max(1, len(hits)),
        filters=RetrievalFilters(),
        max_context_chars=max_context_chars,
        evidence_overfetch=3,
        max_hits_per_document=2,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        evidence=tuple(hits),
    )
    return build_grade_prompt(state)


def classify_placement(size: int | None, size_vram: int | None) -> str:
    """Mirror the inventory's placement rule for one ``/api/ps`` entry."""
    if size is None or size_vram is None:
        return "unknown"
    if size_vram == 0:
        return "cpu"
    return "gpu" if size_vram >= size else "mixed"


def summarize_run(
    *,
    schema: str,
    think: bool,
    num_predict: int,
    prompt_chars: int,
    response: dict[str, Any],
    total_s: float,
    error: str | None = None,
) -> GradeRun:
    """Reduce one ``/api/chat`` response to the numbers the report needs."""
    message = response.get("message") or {}
    content = str(message.get("content") or "")
    thinking = str(message.get("thinking") or "")
    prompt_eval = response.get("prompt_eval_count")
    prompt_ms = (response.get("prompt_eval_duration") or 0) / 1e6
    eval_count = response.get("eval_count")
    eval_ms = (response.get("eval_duration") or 0) / 1e6
    load_ns = response.get("load_duration")
    grades = max_reason = None
    valid = False
    if content:
        try:
            parsed = SCHEMAS[schema].model_validate_json(content)
            valid = True
            rows = list(getattr(parsed, "grades", ()))
            grades = len(rows)
            max_reason = max((len(row.reason) for row in rows), default=0)
        except ValueError:
            valid = False
    return GradeRun(
        schema=schema,
        think=think,
        num_predict=num_predict,
        prompt_chars=prompt_chars,
        prompt_eval_count=prompt_eval,
        prompt_eval_tps=round(prompt_eval / prompt_ms * 1000, 1)
        if prompt_eval and prompt_ms
        else None,
        eval_count=eval_count,
        eval_tps=round(eval_count / eval_ms * 1000, 1) if eval_count and eval_ms else None,
        load_ms=round(load_ns / 1e6, 1) if load_ns is not None else None,
        total_s=round(total_s, 2),
        done_reason=response.get("done_reason"),
        thinking_chars=len(thinking),
        content_chars=len(content),
        json_valid=valid,
        grades=grades,
        max_reason_chars=max_reason,
        error=error,
    )


def render_markdown(runs: list[GradeRun]) -> str:
    """Render the grade runs as one Markdown table."""
    lines = [
        "| schema | think | num_predict | prompt tok | prompt tok/s | out tok | gen tok/s "
        "| load ms | total s | done | thinking chars | JSON | grades | max reason |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        lines.append(
            f"| {run.schema} | {run.think} | {run.num_predict} | {run.prompt_eval_count} "
            f"| {run.prompt_eval_tps} | {run.eval_count} | {run.eval_tps} | {run.load_ms} "
            f"| {run.total_s} | {run.done_reason} | {run.thinking_chars} | {run.json_valid} "
            f"| {run.grades} | {run.max_reason_chars} |"
        )
    return "\n".join(lines)


def _chat(
    client: httpx.Client, url: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], float, str | None]:
    """Send one chat request and return the parsed body, elapsed seconds and an error text."""
    started = time.perf_counter()
    try:
        response = client.post(f"{url}/api/chat", json=payload)
        elapsed = time.perf_counter() - started
        body = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        error = (
            None
            if response.status_code == 200
            else f"HTTP {response.status_code}: {response.text[:200]}"
        )
        return body, elapsed, error
    except httpx.HTTPError as exc:
        return {}, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"


def _payload(
    model: str, prompt: Prompt, *, schema: str, think: bool, num_predict: int, num_ctx: int
) -> dict[str, Any]:
    """Build the ``/api/chat`` request the provider would send, with the chosen knobs."""
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
        "format": SCHEMAS[schema].model_json_schema(),
        "stream": False,
        "think": think,
        "options": {"num_predict": num_predict, "num_ctx": num_ctx, "temperature": 0},
    }


def calibrate(client: httpx.Client, url: str, model: str, prompt: Prompt) -> dict[str, Any]:
    """Compare the model's own prompt token count with the tiktoken encodings."""
    samples = {"grade_prompt": prompt.user, "korean_sample": KOREAN_SAMPLE}
    result: dict[str, Any] = {}
    for name, text in samples.items():
        body, _elapsed, error = _chat(
            client,
            url,
            {
                "model": model,
                "messages": [{"role": "user", "content": text}],
                "stream": False,
                "think": False,
                "options": {"num_predict": 1, "num_ctx": 8192, "temperature": 0},
            },
        )
        counts = {
            enc: len(tiktoken.get_encoding(enc).encode(text, disallowed_special=()))
            for enc in ("cl100k_base", "o200k_base")
        }
        result[name] = {
            "model_prompt_eval_count": body.get("prompt_eval_count"),
            **counts,
            "error": error,
        }
    return result


def truncation_probe(client: httpx.Client, url: str, model: str) -> dict[str, Any]:
    """Send a prompt larger than a tiny window and record how Ollama reacts."""
    text = " ".join(f"token{index}" for index in range(1200))
    body, elapsed, error = _chat(
        client,
        url,
        {
            "model": model,
            "messages": [{"role": "user", "content": f"Repeat the last word only.\n{text}"}],
            "stream": False,
            "think": False,
            "options": {"num_predict": 8, "num_ctx": 512, "temperature": 0},
        },
    )
    return {
        "prompt_eval_count": body.get("prompt_eval_count"),
        "content": str((body.get("message") or {}).get("content") or "")[:80],
        "elapsed_s": round(elapsed, 2),
        "error": error,
    }


def main() -> int:
    """Run the benchmark matrix from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ollama-url", default=os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434")
    )
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--api-url", help="DocReview API origin; /retrieve supplies the evidence")
    parser.add_argument("--evidence-file", help="JSON list of chunk hits instead of --api-url")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max-context-chars", type=int, default=12_000)
    parser.add_argument("--num-predict", default="600,300", help="comma-separated values")
    parser.add_argument("--schema", default="current,bounded", help="comma-separated schemas")
    parser.add_argument("--think", default="true,false", help="comma-separated booleans")
    parser.add_argument("--num-ctx", type=int, default=12_600)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--truncation-probe", action="store_true")
    parser.add_argument("--json", dest="json_path", help="write the full result to this path")
    parser.add_argument("--markdown", action="store_true", help="print a Markdown table")
    args = parser.parse_args()
    if os.environ.get("MODE", os.environ.get("DOCREVIEW_ENVIRONMENT", "dev")) == "prod":
        print("Refusing to load or run a local model in production mode.", file=sys.stderr)
        return 2
    print(
        f"Loading and running {args.model} on {args.ollama_url}; this generates tokens.",
        file=sys.stderr,
    )

    with httpx.Client(timeout=900.0) as client:
        if args.evidence_file:
            with open(args.evidence_file, encoding="utf-8") as handle:
                records = json.load(handle)
        elif args.api_url:
            response = client.post(
                f"{args.api_url}/retrieve",
                json={"query": args.query, "session_profile": {"retrieval_preset": "korean"}},
            )
            response.raise_for_status()
            records = response.json()["results"]
        else:
            parser.error("--api-url or --evidence-file is required")
        hits = hits_from_records(records)
        prompt = grade_prompt(args.query, hits, max_context_chars=args.max_context_chars)
        ps = client.get(f"{args.ollama_url}/api/ps").json()
        loaded = next((m for m in ps.get("models", []) if m.get("name") == args.model), {})
        result: dict[str, Any] = {
            "model": args.model,
            "ollama_url": args.ollama_url,
            "hits": len(hits),
            "prompt": {
                "chars": len(prompt.system) + len(prompt.user),
                "estimate_o200k": estimate_prompt_tokens(prompt, model_name=args.model),
            },
            "runs": [],
        }
        runs: list[GradeRun] = []
        thinks = [
            value.strip().lower() == "true" for value in args.think.split(",") if value.strip()
        ]
        for schema in [value.strip() for value in args.schema.split(",") if value.strip()]:
            for think in thinks:
                for num_predict in [
                    int(value) for value in args.num_predict.split(",") if value.strip()
                ]:
                    for _ in range(args.repeat):
                        payload = _payload(
                            args.model,
                            prompt,
                            schema=schema,
                            think=think,
                            num_predict=num_predict,
                            num_ctx=args.num_ctx,
                        )
                        body, elapsed, error = _chat(client, args.ollama_url, payload)
                        run = summarize_run(
                            schema=schema,
                            think=think,
                            num_predict=num_predict,
                            prompt_chars=result["prompt"]["chars"],
                            response=body,
                            total_s=elapsed,
                            error=error,
                        )
                        runs.append(run)
                        print(
                            f"  {schema} think={think} num_predict={num_predict}: "
                            f"{run.total_s}s out={run.eval_count} valid={run.json_valid} "
                            f"thinking={run.thinking_chars}",
                            file=sys.stderr,
                        )
        result["runs"] = [asdict(run) for run in runs]
        ps = client.get(f"{args.ollama_url}/api/ps").json()
        loaded = next((m for m in ps.get("models", []) if m.get("name") == args.model), loaded)
        result["placement"] = {
            "size": loaded.get("size"),
            "size_vram": loaded.get("size_vram"),
            "context_length": loaded.get("context_length"),
            "placement": classify_placement(loaded.get("size"), loaded.get("size_vram")),
        }
        if args.calibrate:
            result["calibration"] = calibrate(client, args.ollama_url, args.model, prompt)
        if args.truncation_probe:
            result["truncation_probe"] = truncation_probe(client, args.ollama_url, args.model)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    if args.markdown:
        print(render_markdown(runs), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
