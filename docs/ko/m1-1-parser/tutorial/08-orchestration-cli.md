# M1.1 튜토리얼 8 — 자가 복구 루프와 사람이 들여다보는 통로

열두 층이 쌓였다. L13이 그것을 하나의 루프로 묶고, L14가 사람이 들여다볼 통로를 낸다.

L13의 루프는 단순한 순차 실행이 아니다. **검증에 실패하면 규칙을 다시 학습해서 재시도한다.** 폴백이 성립하려면 실패를 감지할 수 있어야 한다는 L12의 전제가 여기서 값을 한다.

**선행 조건:** 튜토리얼 7의 `uv run pytest tests/ingestion/test_04_validate.py -v`와 `tests/ingestion/test_05_profile.py -v`가 전부 통과해야 한다.

## 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| L13 `parse_filing` | **구조 작성 후 호출 순서 검토** | 비싼 작업을 루프 밖으로 끌어올리는 경계 |
| L13 재학습 루프 | 복구 경로를 **직접 구현** | 검증 실패가 어떻게 재시도로 이어지는가 |
| L14 CLI 플래그 | **구조 작성** | 자동화할 수 없는 판단에 통로를 내는 법 |
| `app/ingestion/edgar.py` | **구조 작성** | 코퍼스가 어떻게 고정 스냅샷이 되는가 |

---

## L13 — 오케스트레이션 — 자가 복구 루프

지금까지 만든 걸 하나로 엮는다. 흐름은 이렇다.

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

짧은 함수지만 결정이 세 개 들어 있다.

### 비싼 것은 밖으로 끌어올린다

`soup`을 함수 맨 앞에서 한 번 만들고 계속 돌려쓴다.

이유는 비용 구조다. HTML 파싱이 문서당 0.3~0.7초로 전체 비용의 대부분이고, 판별과 세그멘테이션은 0.1초 남짓이다. 재학습할 때 문서를 다시 파싱하면 가장 비싼 작업을 두 번 하게 된다.

`build_profile(soup, blocks, ...)`이 `soup`을 인자로 받는 시그니처인 것도 이 때문이다. 함수가 스스로 파싱하게 두면 이 재사용이 불가능해진다. **비싼 자원은 가장 바깥에서 만들어 안으로 넘긴다.**

### 성공한 프로파일만 저장한다

재학습 후 `if not r_problems:` 안에서만 `save_profile`을 부른다.

검증에 실패한 프로파일을 저장하면 다음 실행이 그 나쁜 규칙으로 시작한다. 자가 복구 시스템이 스스로를 망가뜨리는 셈이다.

원칙은 **"실패는 상태로 저장하되, 나쁜 규칙은 저장하지 않는다"**이다. `out.parse_status = "needs_profile_update"`로 실패 사실은 남기지만 규칙은 안 바꾼다. (`undefined` 타입은 나쁜 규칙이 아니라 "판별 실패"라는 상태라서 저장한다.)

### 반환값이 3개를 넘으면 객체로 만든다

`ParsedFiling`이 필드가 많은 dataclass인 이유가 있다. 처음엔 4-튜플로 반환했는데, 필드를 하나 추가할 때마다 언패킹하는 호출부가 **전부** 깨졌다([B18](../04-bugs.md#b18)).

객체로 바꾸면 필드를 추가해도 기존 호출부가 그대로 돈다. **반환값이 3개를 넘으면 dataclass를 쓴다**는 게 경험칙으로 쓸 만하다.

### 구현 — 진입점 — 비싼 것은 밖으로 끌어올린다

#### 대상 파일: `app/ingestion/parser.py`

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

코드에서 두 가지만 더 짚는다.

**측정값은 측정한 곳에서 들고 나온다.** `n_blocks`와 `n_chars`를 여기서 채운다. 파싱 결과에 굳이 넣을 필요가 있나 싶지만, 이 값들은 커버리지 검증의 분모다. 안 담아두면 CLI가 검증할 때마다 문서를 다시 파싱해야 한다. 20개 기준으로 40초와 18초의 차이가 났다. **이미 계산한 값을 결과에 담아 나오는 건 거의 공짜다.**

**재학습 결과는 통째로만 승격한다.** `r_problems`가 비었을 때만 `profile, sections, index, problems`를 한 줄에서 한꺼번에 교체한다.

하나씩 따로 바꾸면 "새 섹션인데 옛 프로파일" 같은 모순 상태가 중간에 생긴다. 지금은 예외가 안 나서 괜찮지만, 사이에 코드가 추가되면 그 모순 상태를 보게 된다. **여러 값이 함께 유효해야 한다면 함께 바꾼다.**

### 확인

```bash
uv run pytest tests/ingestion/test_05_profile.py -k converge -v
```

**밟은 함정** — [B18](../04-bugs.md#b18) 4-튜플 반환

---

## L14 — CLI — 자동화할 수 없는 판단을 위한 통로

테스트가 다 통과하는데 왜 CLI가 필요할까. 둘이 잡는 게 다르기 때문이다.

| | 잡는 것 | 성격 |
|---|---|---|
| **pytest** | 회귀. 알려진 값이 변했나 | 통과 / 실패 |
| **CLI** | 탐색. **이게 말이 되나** | 사람이 읽는다 |

pytest는 "Item 15의 블록 수가 어제와 같은가"에 답한다. 그런데 어제 값 자체가 틀렸다면 어떨까? 테스트는 그 틀린 값을 성실히 지킬 뿐이다.

`--headings`로 출력한 오프셋을 원본 HTML에서 열어 대조하는 것, `--sections`의 분량 분포를 보고 "재무제표가 Item 15에 있는 게 맞나" 판단하는 것 — 이런 건 자동화할 수 없다. 골든값을 처음 정할 때도, 의심스러울 때도 사람이 봐야 한다.

[05-verify.md](../05-verify.md)의 최종확인④가 그 절차다.

이제 `app/ingestion/parser.py` 끝에 다음 CLI를 작성한다. 모든 분기는 지금까지 만든 공개 함수를 호출하며 파싱 규칙을 다시 구현하지 않는다.

#### `app/ingestion/parser.py` 확장 — 검사 CLI

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

### 구현 — CLI — 사람이 들여다보는 경로

`if __name__ == "__main__":` 블록에 있다(`parser.py` 끝).

| 플래그 | 하는 일 | 프로파일 필요 |
|---|---|---|
| `--ticker NVDA` | 한 회사만 | — |
| `--file <경로>` | 파일 하나만 | — |
| `--blocks` | 1~2단계: 블록 수·표블록 수 | ✗ (파싱 전) |
| `--sections` | 섹션별 본문량·표 개수·상태 | ✅ |
| `--headings` | 각 Item 헤딩의 블록 번호·**원본 오프셋**·뒤따르는 본문 | ✅ |
| `--coverage` | 섹션 본문 합 / 문서 전체 | ✅ |
| `--items` | SEC Item 목록 대조 | ✅ |
| `--profile` | 학습된 프로파일 JSON | ✅ |

인자 없이 실행하면 20문서 전체를 파싱하고 집계를 낸다.

> **없는 플래그** — `--all`, `--allow-llm`, `--disable`. 이전 설계 문서에 나오지만 코드에 없다([02-spec.md](../02-spec.md)의 "설계됨 · 미구현").

CLI 루프에서 `--blocks`만 `parse_filing` 호출 **앞에** 있고 `continue`로 빠지는 게 눈에 띌 것이다.

블록화는 파싱 파이프라인의 맨 아래층이다. 그런데 `parse_filing`을 거쳐야만 블록을 볼 수 있다면, 블록화 버그를 진단하려고 프로파일 학습이 성공하기를 기다려야 한다. **의존 방향이 거꾸로다.**

디버깅 도구는 진단하려는 대상보다 적은 것에 의존해야 한다. 그래서 `--blocks`는 `normalize`와 `leaf_blocks`만 부르고 끝낸다.

### 확인

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

이 출력을 원본과 대조하는 법은 [05-verify.md](../05-verify.md)의 최종확인④에 있다.

---

## 코퍼스 수집 모듈까지 완성하기

파서가 직접 import하지는 않지만, M1.1의 정식 파일 목록에는 SEC 스냅샷과 manifest를 만드는 `app/ingestion/edgar.py`도 포함된다. 아래와 같이 작성한다. 현재 튜토리얼은 이미 고정된 `data/corpus`를 사용하므로 여기서 네트워크 수집을 다시 실행하지 않는다. 실제로 갱신할 때는 `USER_AGENT`의 연락처부터 자신의 값으로 바꾼다.

#### `app/ingestion/edgar.py` 생성 — 코퍼스 수집기

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


## 이제 완성된 CLI로 레이어를 다시 본다

앞에서 미뤄 둔 CLI 명령은 이제 모두 실행 가능하다. 블록화, 일반 헤딩 세그멘테이션, `xref` 조인, 저장된 프로파일을 차례로 확인한다.

```bash
uv run python -m app.ingestion.parser --blocks
uv run python -m app.ingestion.parser --ticker NVDA --sections
uv run python -m app.ingestion.parser --ticker INTC --sections
uv run python -m app.ingestion.parser --ticker AMD --profile
```

프로파일 수렴을 눈으로 확인하려면 아래 명령이 기존 `data/profiles`를 삭제한다는 점을 먼저 확인한다. 추적할 프로파일이 없다면 세 번 실행했을 때 마지막 실행은 모두 `saved`가 되고, 집계는 `{number: 15, xref: 5}`가 된다.

```bash
rm -rf data/profiles
uv run python -m app.ingestion.parser          # 1회차: 학습
uv run python -m app.ingestion.parser          # 2회차
uv run python -m app.ingestion.parser          # 3회차: 전부 saved
```

마지막으로 M1.1 전체 계약을 한 번에 확인한다.

```bash
uv run pytest tests/ingestion/test_01_blocks.py tests/ingestion/test_02_rules.py tests/ingestion/test_03_segment.py tests/ingestion/test_04_validate.py tests/ingestion/test_05_profile.py tests/ingestion/test_06_xref.py tests/ingestion/test_07_coverage.py tests/ingestion/test_08_items.py -q
```

---

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **재학습 루프가 성립하려면 앞 레이어가 무엇을 보장해야 하는가?**
  - **답:** 앞 레이어는 결정적인 파싱 입력을 만들고, 무엇보다 검증이 잘못된 결과를 알아내야 한다. 실패를 감지하지 못하면 재학습을 시작할 수 없고, 재시도 결과가 검증되지 않으면 새 프로파일을 안전하게 채택할 수 없다.
- **비싼 작업을 루프 밖으로 끌어올리는 경계는 어디인가?**
  - **답:** `parse_filing`의 바깥 경계에서 원문을 읽고 파싱해 `soup`과 블록을 한 번만 만든 뒤 판별·세그멘테이션·재학습에 그대로 넘긴다. 재시도에서는 더 싼 판단 단계만 반복한다.
- **CLI 플래그가 자동화된 테스트와 다르게 답하는 질문은 무엇인가?**
  - **답:** 테스트는 알려진 값이 바뀌었는지 답하고, CLI는 그 값 자체가 타당한지와 출력한 원문 오프셋이 실제 헤딩·본문을 가리키는지 사람이 판단하게 한다. 골든 테스트는 처음부터 틀린 값도 충실히 지킬 수 있다.
- **프로파일 수렴이 2회차가 아니라 3회차인 이유는 무엇인가?**
  - **답:** `default_year`는 항상 가장 최근 저장 연도로 바뀌는데 `expected_items`는 연도마다 다르다. 자기 항목이 없는 옛 연도가 최신 개수로 검증받아 실패한 뒤 실행마다 검증된 재학습으로 채워지므로, 3회차가 되어야 전부 저장된 프로파일만 쓴다.
- **`edgar.py`를 정식 파일에 포함하면서도 여기서 실행하지 않는 이유는 무엇인가?**
  - **답:** 이 파일은 실제 SEC 코퍼스 수집기지만 실행하면 네트워크를 통해 고정된 스냅샷과 매니페스트가 바뀔 수 있다. 튜토리얼은 재현성을 위해 체크인된 코퍼스를 쓰며, 실제 갱신 전에는 유효한 SEC `USER_AGENT`도 설정해야 한다.

---

[← 이전: 프로파일과 검증](07-profile-validate.md) · [모듈 개요](../03-build.md)
