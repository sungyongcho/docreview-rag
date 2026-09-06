# M1.1 Tutorial 8 — The self-healing loop and the path for human inspection

Twelve layers are stacked. L13 binds them into one loop, and L14 opens the path a human looks through.

L13's loop is not plain sequential execution. **When validation fails, it relearns the rules and retries.** L12's premise — that a fallback only works if failure is detectable — pays off here.

**Prerequisite:** Tutorial 7's `uv run pytest tests/ingestion/test_04_validate.py -v` and `tests/ingestion/test_05_profile.py -v` pass in full.

## What to write and where to implement it yourself

| Stretch | Learning action | What to take away |
|---|---|---|
| L13 `parse_filing` | **Write the structure, then review the call order** | the boundary that hoists expensive work out of the loop |
| L13 relearn loop | **Implement** the recovery path | how a validation failure becomes a retry |
| L14 CLI flags | **Write the structure** | opening a path for judgments that cannot be automated |
| `app/ingestion/edgar.py` | **Write the structure** | how the corpus becomes a fixed snapshot |

---

## L13 — Orchestration — the self-healing loop

Everything built so far gets connected. The flow is this.

```
load profile → bootstrap-learn if absent
       ↓
   segmentation
       ↓
    validation
       ↓
problems? → relearn → segment again → validate again
              ↓ on success
        save new profile + swap in results
```

A short function carrying three decisions.

### Hoist the expensive work outward

`soup` is built once at the top of the function and reused throughout.

The reason is the cost profile. HTML parsing runs 0.3–0.7 seconds per document, most of the total, while detection and segmentation take about 0.1 seconds. Reparsing the document when relearning pays the most expensive step twice.

That is also why `build_profile(soup, blocks, ...)` takes `soup` as a parameter. Let the function parse for itself and this reuse becomes impossible. **Expensive resources are created at the outermost point and passed inward.**

### Only successful profiles get saved

Only inside `if not r_problems:` after relearning is `save_profile` called.

Saving a profile that failed validation makes the next run start from those bad rules — a self-healing system damaging itself.

The principle is **"store failure as state, but do not store bad rules."** `out.parse_status = "needs_profile_update"` records that it failed without changing the rules. (The `undefined` type is not a bad rule but a state — "detection failed" — so it is stored.)

### More than three return values means an object

There is a reason `ParsedFiling` is a dataclass with many fields. It started as a 4-tuple, and every time a field was added **every** unpacking caller broke ([B18](../04-bugs.md#b18)).

With an object, adding a field leaves existing callers working. **More than three return values call for a dataclass** is a serviceable rule of thumb.

### Build — Entry point — hoist the expensive work outward

#### Target file: `app/ingestion/parser.py`

<!-- src: app/ingestion/parser.py::parse_filing -->
```python
def parse_filing(entry: dict) -> tuple[ParsedFiling, dict]:
    """Run one filing through profile loading, parsing, validation, and relearning.

    Return the parsed result and the profile used.
    """
    ticker, year = entry["ticker"], int(entry["report_date"][:4])
    doc_id = f"{ticker}-FY{year}"
    raw = read_source(entry["file"])
    soup = normalize(raw)
    blocks = leaf_blocks(soup)
    offsets = line_offsets(raw)

    out = ParsedFiling(
        doc_id=doc_id,
        ticker=ticker,
        cik=str(entry.get("cik", "")),
        form="10-K",
        filing_date=entry.get("filing_date", ""),
        report_period=entry.get("report_date", ""),
        fiscal_year=year,
        accession=entry.get("accession", ""),
        source_url=entry.get("url", ""),
        source_length=len(raw),
        source_sha256=source_digest(raw),
        n_blocks=len(blocks),
        n_chars=sum(len(b.get_text(" ", strip=True)) for b in blocks),
    )

    profile = load_profile(ticker, year)
    out.profile_used = "saved"
    if profile is None:
        profile = build_profile(soup, blocks, doc_id)
        save_profile(ticker, year, profile)
        out.profile_used = "bootstrap"

    sections, index = segment(soup, blocks, profile["segmentation"], offsets, len(raw))
    problems = validate(sections, profile, index) if sections else ["zero sections"]

    if problems:
        # On failure, relearn from this filing and store only this year after success (F4).
        relearned = build_profile(soup, blocks, doc_id)
        r_sections, r_index = segment(soup, blocks, relearned["segmentation"], offsets, len(raw))
        r_problems = validate(r_sections, relearned, r_index) if r_sections else ["zero sections"]
        if not r_problems:
            save_profile(ticker, year, relearned)  # save only a successful profile
            profile, sections, index, problems = relearned, r_sections, r_index, r_problems
            out.profile_used = "relearned"

    out.sections = sections
    out.item_index = index
    out.warnings = problems
    out.parse_status = "parsed" if not problems else "needs_profile_update"
    out.segment_type = profile["segmentation"]["type"]
    return out, profile
```

Two more points from the code.

**Measurements travel out from where they were taken.** `n_blocks` and `n_chars` are filled here. It seems unnecessary to put them in a parse result, but they are the denominators for coverage validation. Without them the CLI reparses each document at validation time — forty seconds versus eighteen across twenty files. **Carrying an already-computed value out in the result is nearly free.**

**Relearned results are promoted only as a whole.** Only when `r_problems` is empty are `profile, sections, index, problems` swapped in one statement.

Changing them one at a time creates an intermediate state of contradiction — "new sections with the old profile." No exception occurs today, but insert code between and you will see that state. **When several values must be valid together, change them together.**

### Verify

```bash
uv run pytest tests/ingestion/test_05_profile.py -k converge -v
```

**Pitfall encountered** — [B18](../04-bugs.md#b18), returning a 4-tuple

---

## L14 — CLI — a path for judgments that cannot be automated

Why keep a CLI when the tests all pass? Because the two catch different things.

| | What it catches | Nature |
|---|---|---|
| **pytest** | Regressions: did a known value change? | pass / fail |
| **CLI** | Exploration: **does this make sense?** | Read by a person |

pytest answers "is Item 15's block count the same as yesterday?" But what if yesterday's value was itself wrong? The test faithfully defends the wrong number.

Opening the offsets printed by `--headings` against the source, or looking at the size distribution from `--sections` and judging "should the financial statements really be under Item 15?" — these cannot be automated. A person has to look, both when the golden values are first set and whenever something is in doubt.

Final check ④ in [05 verification](../05-verify.md) is that procedure.

Now write this CLI at the end of `app/ingestion/parser.py`. Every branch calls the public functions built above instead of reimplementing parsing rules.

#### Extend `app/ingestion/parser.py` — inspection CLI

```python
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="10-K 파서 — 단계별 확인용")
    ap.add_argument("--ticker", help="한 회사만 (예: NVDA)")
    ap.add_argument("--file", help="파일 하나만 (경로)")
    ap.add_argument("--blocks", action="store_true", help="1~2단계: 블록화 결과")
    ap.add_argument("--sections", action="store_true", help="섹션별 본문량·표 개수")
    ap.add_argument(
        "--headings", action="store_true", help="각 Item 헤딩의 블록 번호·원본 오프셋·뒤따르는 본문"
    )
    ap.add_argument(
        "--coverage", action="store_true", help="섹션 본문 합 / 문서 전체 — 버려진 텍스트를 잡는다"
    )
    ap.add_argument(
        "--items", action="store_true", help="SEC Item 목록 대조 — 헤딩 누락·오탐을 잡는다"
    )
    ap.add_argument("--profile", action="store_true", help="학습된 프로파일 JSON")
    a = ap.parse_args()

    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    targets = [e for e in manifest if not a.ticker or e["ticker"] == a.ticker]
    if a.file:
        targets = [e for e in manifest if e["file"] == a.file]
    if not targets:
        raise SystemExit(f"대상 없음 (ticker={a.ticker} file={a.file})")

    stats: dict[str, int] = {}
    for entry in sorted(targets, key=lambda e: (e["ticker"], e["report_date"])):
        # 1~2단계는 파싱 전이라 따로 처리
        if a.blocks:
            soup = normalize(read_source(entry["file"]))
            blocks = leaf_blocks(soup)
            tables = [b for b in blocks if b.name == "table"]
            doc_id = f"{entry['ticker']}-FY{entry['report_date'][:4]}"
            print(
                f"{doc_id:12} 블록 {len(blocks):5,}  표블록 {len(tables):4}  "
                f"문서표 {len(soup.find_all('table')):4}"
            )
            continue

        r, profile = parse_filing(entry)
        stats[r.segment_type] = stats.get(r.segment_type, 0) + 1

        if a.profile:
            print(f"--- {r.doc_id} ({r.profile_used}) ---")
            print(json.dumps(profile, indent=2, ensure_ascii=False))
            continue

        if a.headings:
            raw = read_source(entry["file"])
            print(f"--- {r.doc_id} ({r.segment_type}) ---")
            for sec in r.sections:
                head = raw[sec.source_pos : sec.source_pos + 46] if sec.source_pos else ""
                body = next((b.text for b in sec.blocks if b.kind == "paragraph"), "")
                print(
                    f"  {sec.item or '-':4} blk{str(sec.block_index):>6} "
                    f"pos{str(sec.source_pos):>10}  {sec.reported_title[:42]}"
                )
                print(f"       원본 {head!r}")
                print(f"       본문 {body[:54]!r}")
            continue

        if a.items:
            # 커버리지는 헤딩 누락을 못 잡는다(앞 섹션이 흡수해 총량 불변).
            # SEC가 정한 Item 목록과 대조해야 경계가 맞는지 알 수 있다.
            got = [s.item for s in r.sections if s.item]
            missing = [i for i in ORDER if i not in got]
            extra = [i for i in got if i not in ORDER]
            # 1C(2023 신설) · 9C(2021 신설) · 16(선택 항목)은 부재가 정상
            odd = [m for m in missing if m not in ("1C", "9C", "16")]
            print(
                f"{r.doc_id:12} {len(got):2}개  누락={missing or '-'}  "
                f"과잉={extra or '-'}{'  ★' if (odd or extra) else ''}"
            )
            continue

        body = sum(len(b.text) for s in r.sections for b in s.blocks)
        tbl_chars = sum(
            len(BeautifulSoup(b.html, "html.parser").get_text(" ", strip=True))
            for s in r.sections
            for b in s.blocks
            if b.kind == "table" and b.html
        )

        if a.coverage:
            pct = (body + tbl_chars) / r.n_chars * 100 if r.n_chars else 0
            print(
                f"{r.doc_id:12} 전체 {r.n_chars:>9,}  섹션 {body + tbl_chars:>9,}  "
                f"커버 {pct:5.1f}%{'   ★낮음' if pct < 90 else ''}"
            )
            continue

        items = [s.item for s in r.sections if s.item]
        tbl = sum(1 for s in r.sections for b in s.blocks if b.kind == "table")
        print(
            f"{r.doc_id:12} {r.parse_status:20} type={r.segment_type:9} "
            f"{r.profile_used:10} items={len(items):2} 본문={body:>8,} 표={tbl:3}"
        )
        for w in r.warnings:
            print(f"               ⚠ {w}")

        if a.sections:
            for s in r.sections:
                n = sum(len(b.text) for b in s.blocks)
                t = sum(1 for b in s.blocks if b.kind == "table")
                flag = "" if s.status == "parsed" else f"  [{s.status}]"
                print(
                    f"     Item {s.item or '-':4} {n:>8,}자 표{t:3}  {s.reported_title[:52]}{flag}"
                )

    if not (a.blocks or a.profile or a.headings):
        print(f"\n집계: {stats}")
```

### Build — CLI — the path for human inspection

They live in the `if __name__ == "__main__":` block at the end of `parser.py`.

| Flag | Action | Profile required |
|---|---|---|
| `--ticker NVDA` | One company only | — |
| `--file <경로>` | One file only | — |
| `--blocks` | Stages 1 through two: block and table-block counts | ✗ (before parsing) |
| `--sections` | Body size, table count, and status by section | ✅ |
| `--headings` | Block number, **source offset**, and following body for each Item heading | ✅ |
| `--coverage` | Sum of section bodies / entire document | ✅ |
| `--items` | Compare with the SEC Item list | ✅ |
| `--profile` | Learned profile JSON | ✅ |

Running without arguments parses all twenty documents and prints aggregates.

> **Flags that do not exist** — `--all`, `--allow-llm`, and `--disable`. They appear in an earlier design document but not in code ("Designed · not implemented" in [02 specification](../02-spec.md)).

You will notice that only `--blocks` sits **before** the `parse_filing` call in the CLI loop and exits with `continue`.

Blockification is the bottom layer of the parsing pipeline. If the only way to see blocks were through `parse_filing`, diagnosing a blockification bug would first require profile learning to succeed. **The dependency runs backwards.**

A debugging tool must depend on less than the thing it diagnoses. So `--blocks` calls only `normalize` and `leaf_blocks` and stops.

### Verify

```bash
uv run python -m app.ingestion.parser --file data/corpus/NVDA/2024-02-21_0001045810-24-000029.html --headings
```

```
--- NVDA-FY2024 (number) ---
  1    blk    65 pos    198007  Item 1. Business
       원본 '<div style="margin-bottom:6pt;margin-top:12pt;'
       본문 'NVIDIA pioneered accelerated computing to help solve t'
  1A   blk   215 pos    289841  Item 1A. Risk Factors
       원본 '<div style="margin-bottom:6pt;margin-top:12pt;'
       본문 'The following risk factors should be considered in add'
```

Final check ④ in [05 verification](../05-verify.md) explains how to compare this output with the source.

---

## Complete the corpus collector

The parser does not import it directly, but M1.1 also owns `app/ingestion/edgar.py`, which creates SEC snapshots and the manifest. Write it as shown below. This tutorial uses the already pinned `data/corpus`, so do not run a network refresh here. Before an actual refresh, replace the contact details in `USER_AGENT` with your own.

#### Create `app/ingestion/edgar.py` — corpus collector

```python
import json
from pathlib import Path
import time

import httpx

CIKS = {"NVDA": 1045810, "AMD": 2488, "INTC": 50863, "MU": 723125}
FILING_YEARS = range(2020, 2025)  # filingDate years 2020-2024 (about five per company)
USER_AGENT = "filing-rag research dev@sungyongcho.com"  # SEC requires contact details
CORPUS = Path("data/corpus")


def _pick_10k(block: dict) -> list[dict]:
    """Select target-year 10-K filings from one recent or older submissions block.

    The SEC represents filings as parallel arrays: values at the same index belong
    to the same filing. ``strict=True`` matters because ordinary ``zip`` silently
    stops at the shortest array and can drop trailing filings without reporting a
    corpus gap. A loud failure is safer than silent loss. All eight recent/older
    responses measured across the four companies had matching lengths.
    """
    rows = zip(
        block["form"],
        block["accessionNumber"],
        block["filingDate"],
        block["reportDate"],
        block["primaryDocument"],
        strict=True,
    )
    return [
        {"accession": acc, "filing_date": fd, "report_date": rd, "primary_doc": doc}
        for form, acc, fd, rd, doc in rows
        if form == "10-K" and int(fd[:4]) in FILING_YEARS
    ]


def fetch_10k_list(client: httpx.Client, cik: int) -> list[dict]:
    """Return every target 10-K from recent and older submission files."""
    r = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    r.raise_for_status()
    filings = r.json()["filings"]
    result = _pick_10k(filings["recent"])
    # Older filings live in separate files; fetch each file that overlaps the target years.
    for extra in filings.get("files", []):
        if int(extra["filingFrom"][:4]) <= max(FILING_YEARS):  # overlaps the target period
            time.sleep(0.2)
            er = client.get(f"https://data.sec.gov/submissions/{extra['name']}")
            er.raise_for_status()
            result += _pick_10k(er.json())
    return result


def download(client: httpx.Client, ticker: str, cik: int, filing: dict) -> dict:
    acc = filing["accession"].replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{filing['primary_doc']}"
    dest = CORPUS / ticker
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{filing['filing_date']}_{filing['accession']}.html"
    if not path.exists():  # idempotent: do not download an existing snapshot again
        r = client.get(url)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    return {"ticker": ticker, "cik": cik, **filing, "file": str(path), "url": url}


def main() -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
        for ticker, cik in CIKS.items():
            filings = fetch_10k_list(client, cik)
            print(f"{ticker}: {len(filings)}개 10-K")
            for filing in filings:
                manifest.append(download(client, ticker, cik, filing))
                time.sleep(0.2)  # respect the SEC rate guidance (at most 10 requests/s)
    (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"총 {len(manifest)}개 filing → {CORPUS}")


if __name__ == "__main__":
    main()
```


## Revisit the layers through the completed CLI

Every CLI command deferred earlier is now runnable. Inspect blockification, ordinary heading segmentation, the `xref` join, and the saved profile in that order.

```bash
uv run python -m app.ingestion.parser --blocks
uv run python -m app.ingestion.parser --ticker NVDA --sections
uv run python -m app.ingestion.parser --ticker INTC --sections
uv run python -m app.ingestion.parser --ticker AMD --profile
```

To inspect profile convergence manually, first note that the next command deletes the existing `data/profiles` directory. If there are no profiles you need to preserve, the third pass should use `saved` throughout and print the aggregate `{number: 15, xref: 5}`.

```bash
rm -rf data/profiles
uv run python -m app.ingestion.parser          # 1회차: 학습
uv run python -m app.ingestion.parser          # 2회차
uv run python -m app.ingestion.parser          # 3회차: 전부 saved
```

Finally, verify the complete M1.1 contract in one run.

```bash
uv run pytest tests/ingestion/test_01_blocks.py tests/ingestion/test_02_rules.py tests/ingestion/test_03_segment.py tests/ingestion/test_04_validate.py tests/ingestion/test_05_profile.py tests/ingestion/test_06_xref.py tests/ingestion/test_07_coverage.py tests/ingestion/test_08_items.py -q
```

---

## What you should be able to explain now

- **What must the earlier layers guarantee for the relearn loop to work at all?**
  - **Answer:** They must produce deterministic parse inputs and, most importantly, validation must recognize a bad result. Without detectable failure there is no trigger to relearn, and without a validated retry there is no safe profile to promote.
- **Where is the boundary that hoists expensive work out of the loop?**
  - **Answer:** `parse_filing` reads and parses the source and builds blocks once at its outer boundary, then passes the same `soup` and blocks into detection, segmentation, and relearning. The retry repeats only the cheaper decisions.
- **Which questions does a CLI flag answer that an automated test does not?**
  - **Answer:** Tests answer whether known values regressed; the CLI helps a person judge whether those values make sense and whether printed source offsets really point at the claimed headings and body. A golden test can faithfully preserve a value that was wrong from the start.
- **Why does profile convergence take three passes rather than two?**
  - **Answer:** `default_year` always moves to the latest saved year, while `expected_items` changes across years. Older years without their own entry can therefore fail against the latest count and are filled by validated relearning over successive passes; only the third pass uses saved profiles throughout.
- **Why is `edgar.py` a canonical file that this tutorial does not run?**
  - **Answer:** It is the project's real SEC corpus collector, but running it performs a network refresh and can change the pinned snapshots and manifest. The tutorial uses the checked-in corpus for reproducibility and also requires the user to set a valid SEC `USER_AGENT` before any real refresh.

---

[← Previous: Profiles and validation](07-profile-validate.md) · [Module overview](../03-build.md)
