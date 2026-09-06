# M1.1 Spec

> This document defines **what to build**. For how to implement it, see [03-build.md](03-build.md). Every rationale links to an F-number in [01-findings.md](01-findings.md).

---

## In one sentence

**The SEC defines the "content" of a 10-K (Part/Item), but not its "HTML layout."** The parser therefore manages each company's distinct document structure as a **profile (data)**, while a single `segmentation.type` selects the parsing strategy for deterministic execution.

All twenty current files are parsed without an LLM.

---

## 1. Premise: what is fixed and what varies

**What the SEC fixes** — store these as code constants.

| Part | Items | Content |
|---|---|---|
| I | 1, 1A, 1B, 1C, 2, 3, 4 | Business, risks, unresolved comments, cybersecurity (2023+), properties, legal proceedings, mine safety |
| II | 5, 6, 7, 7A, 8, 9, 9A, 9B, 9C | Stock, (reserved), MD&A, market risk, **financial statements**, accounting disagreements, controls, other information |
| III | 10, 11, 12, 13, 14 | Directors and officers, compensation, ownership, related parties, audit fees — **mostly incorporated from the proxy** |
| IV | 15, 16 | Exhibits and schedules, summary |

Each Item's standard title and standard order are also fixed. → `CANONICAL`, `ORDER`, and `PART_OF` in the code.

**What the SEC does not prescribe** — manage these in company profiles.

- The HTML representation of titles ([F1](01-findings.md#f1): no semantic tags, only inline CSS)
- Font, size, and whether a heading is inside a table ([F3](01-findings.md#f3), [F4](01-findings.md#f4))
- Possible rearrangement of Item order
- **The mechanism that divides the body into Items at all** ([F5](01-findings.md#f5), [F6](01-findings.md#f6))

The last point is the design fork. **The assumption that every 10-K has Item headings is false.**

---

## 2. Processing stages

```
① 정규화       HTML → 의미 있는 트리
② 블록화       트리 → 순서 있는 블록 리스트
③ 세그멘테이션  블록 리스트 → Item 섹션들      ← 프로파일이 지배하는 유일한 단계
④ 검증         섹션들이 말이 되는가
⑤ 출력         ParsedFiling
```

It matters that the profile controls only stage ③. Stages ① and ② are identical regardless of document type, while only the criteria for ④ vary by type.

---

## 3. Segment type — five variants

A single `segmentation.type` determines the parsing strategy. The defining question is **"where does the Item number come from?"**

| `type` | Definition |
|---|---|
| **`number`** | SEC Item numbers appear literally in the body headings, **and** those headings share a consistent style. Because the number itself is authoritative, filter headings with style rules and read the number directly. |
| **`sec_canonical`** | Item numbers are absent, **but** heading titles match the SEC's standard titles. Filter headings, then compare their titles against the SEC canonical-title table (a code constant). |
| **`custom_title`** | Neither numbers nor standard titles appear; the company uses its own vocabulary. Measurements cannot identify the Item, so compare titles against a title→Item mapping table (`order`). |
| **`xref`** | The body has no Item boundaries at all; instead, the SEC-mandated Cross-Reference Index maps Items to pages. With no headings to filter, join the index and the company's table of contents by page to establish boundaries. |
| **`undefined`** | Every classifier failed. With no evidence to rely on, defer the document for human review. |

Why not `custom_item`? The name is `custom_title` because **the SEC defines the Item, so the Item itself cannot be custom.** Only the company's title for that Item is custom.

### Mechanical comparison

| | `number` | `sec_canonical` | `custom_title` | `xref` | `undefined` |
|---|---|---|---|---|---|
| **Headings present?** | Yes | Yes | Yes | No Item headings | — |
| **Basis for Item identity** | Number in the heading | SEC canonical-title table | `order` mapping table | Document's index table | None |
| **Boundary method** | Heading→next heading | Heading→next heading | Heading→next heading | Page ranges | — |
| **Payload** | `rules` | `rules` | `rules` + `order` | None | None |
| **This corpus** | 15/20 | 0/20 | 0/20 | 5/20 | 0/20 |

The point is how the three axes diverge.

- `number`, `sec_canonical`, and `custom_title` — **the boundary method is the same; only the basis for identity differs.** The same traversal loop changes only its comparison target.
- `sec_canonical` and `custom_title` — **even the comparison operation is the same; only the table's source differs.** They remain separate types because different actors fill their payloads (measurement vs external input).
- `xref` — **all three axes differ.** It is therefore also the only type with no payload.

---

## 4. Segmentation logic

Parsing consists of two independent questions.

> **A. Is this block a heading?** → `rules` (style only) **B. Which Item does this heading represent?** → depends on the type

### 4.1 `number` / `sec_canonical` / `custom_title` — shared structure

Traverse the blocks in order and, for each block:

1. **Answer B first**

   | `type` | Comparison target |
   |---|---|
   | `number` | Item number written in the block text (`ITEM_RE`) |
   | `sec_canonical` | SEC canonical-title table (the `CANONICAL` code constant) |
   | `custom_title` | `order` array — exact title match |

2. **Then evaluate A** — the block is a heading if it passes any entry in `rules` 3. If it is a heading, begin a new section; otherwise append it to the current section body

**B runs before A for cost reasons.** Text regexes and dictionary lookups finish immediately, while `block_props()` scans CSS several times with regexes. Only about twenty of 2,400blocks are Item headings, so most fail at B without ever reaching A.

### Rule-evaluation convention

Without an explicit convention, every rule author will interpret these fields differently.

| Convention | Meaning |
|---|---|
| Omitted key | No constraint |
| Number | **At least** (`font_size: 14` rejects values below 14pt) |
| Boolean or string | Exact match |
| `in_table` | `false`=outside tables only, `true`=unconstrained (**asymmetric**) |
| Entire list | A block is a heading if it passes any entry |

`rules` is an **array** because a company may use multiple heading formats.

[F4](01-findings.md#f4) requires the asymmetry of `in_table`. It is inelegant, but when measurements demand it, follow the evidence and make the convention prominent.

**Conditions are purely stylistic** — contextual conditions such as following-body volume or repetition count do not exist in the rule vocabulary. [F13](01-findings.md#f13) explains why, and [B13](04-bugs.md#b13) records the cost.

### 4.2 `xref` — page join

Searching for headings by traversing blocks does not work ([F5](01-findings.md#f5)). Instead:

```
1. 두 표를 찾는다        색인표(Item N. 셀 5행↑) + 기업 목차표(제목|쪽수 10행↑)
2. 색인표를 해석한다      Item → (제목, 페이지 구간들, 상태)
3. 목차표를 해석한다      서사 제목 → 시작 페이지
4. 본문 위치를 찾는다      서사 제목이 본문 어느 블록에서 시작하나
5. Item을 배정한다        페이지 구간 겹침으로
6. 누락을 2차 수색한다     목차엔 없지만 색인표에 페이지가 있는 Item
7. 경계를 보정한다        헤딩이 이미지인 구간 (F8)
8. Item별로 합친다        같은 Item에 배정된 서사 섹션들을 한 Section으로
```

Every trap encountered at each stage is documented in [section 04 covering L8 in the bug guide](04-bugs.md#l8--segmentation-b-xref-page-join): stage two in [B01](04-bugs.md#b01), [B02](04-bugs.md#b02), and [B03](04-bugs.md#b03); stage four in [B10](04-bugs.md#b10); stage five in [B08](04-bugs.md#b08); and stage seven in [B06](04-bugs.md#b06) and [B07](04-bugs.md#b07).

**Item-assignment priority** (tie-breaking):

```
1. 제목 단어 겹침이 많은 쪽
2. 덮는 구간이 좁은 쪽        ← Item의 총 페이지 폭이 아니라 '덮는 구간 하나'의 폭
3. Item 번호가 짧은 쪽         ← 완전 동점 시 결정성 확보
```

Assign each section to only one Item. **The same block is never loaded into two Items.** (The same *text* may appear in two Items when the source itself includes it twice.)

**Status classification** — the index table states it directly:

| Index-table cell | Status |
|---|---|
| Contains page ranges | `parsed` (**final authority** — [B03](04-bugs.md#b03)) |
| No pages + "Not applicable" | `empty_disclosure` |
| No pages + reference marker `(a)` | `incorporated_by_reference` (preserve the footnote sentence as the source) |

---

## 5. Profile lifecycle

### Loading

```
data/profiles/{TICKER}.json 있나?
 ├ 없음 → 부트스트랩 (아래 '학습')
 └ 있음 → profiles[요청연도] 있나?
           ├ 있음 → 그것
           └ 없음 → profiles[default_year]
```

### Parsing and validation

```
프로파일로 파싱 → 검증
 ├ 통과 → 끝
 └ 실패 → 이 문서로 재학습 → 재파싱 → 검증
           ├ 통과 → profiles[이 연도]에 저장   (연도 중간 레이아웃 변경 대응, F4)
           └ 실패 → 실패 상태로 반환 (★나쁜 규칙은 저장하지 않는다)
```

> **Convergence takes three runs, not two.** Because `expected_items` varies by year and `default_year` points to the latest year, an older year with missing Items must relearn once. The process is self-healing but not idempotent; see [04-bugs.md](04-bugs.md#profile-convergence-takes-three-passes-not-two) for details.

### Learning (type detection)

When no profile exists or validation fails, determine the type by **measuring that document**. Try the detectors in order and adopt the first one that succeeds.

```
① number   측정 — 굵은 "Item N" 블록이 5개 이상 있나
② xref     측정 — 색인표 + 목차표가 둘 다 있나
③ undefined  ← 여기가 현재 코드의 끝
```

**There is a reason for the order of ① and ②.**

- ① is the most common and cheapest option (a text regex).
- **② must not precede ①.** A normal 10-K's **table of contents** also looks like `Item 1. Business … 3`, making it indistinguishable from an index table. It is safe to use ② only after confirming that the body has no Item headings.

Measured cost: complete detection takes **0.06~0.11seconds**. The dominant cost, HTML parsing (0.31~0.69seconds), is paid once under any strategy, and detection shares its result.

Each detection function acts as both a **classifier and a payload builder**. Its return value is the answer: `{}` means "not my type," while a populated value means "my type, with configuration complete."

---

## 6. Validation

The criteria differ by type.

**`number` / `sec_canonical` / `custom_title`**

| Check | Requirement |
|---|---|
| Count | Must match `expected_items` exactly |
| Order | For `custom_title`, follow `order`; otherwise use standard SEC order |
| Duplicates | Fail if the same Item appears twice |
| Required | Every entry in `must_have` must be present |
| **Content** | For core Items (1, 1A, 7, 8), fail if at least `CORE_THIN_COUNT`(2items) contain fewer than `CORE_THIN_BLOCKS`(20blocks) |

The final check matters. **When TOC entries are mistaken for headings, count, order, and duplicate checks can all be perfect even though there is no content** ([B10](04-bugs.md#b10)). Structural checks alone cannot catch this failure.

**`xref`**

| Check | Requirement |
|---|---|
| ~~Order~~ | Meaningless — Items are expected to be scattered through the document ([F7](01-findings.md#f7)) |
| ~~Duplicates~~ | Meaningless — sections are already combined into one per Item |
| **Coverage** | Can every Item in the index be explained by {body assigned / no disclosure / incorporated by reference}? |
| Required | `must_have` |
| Thin sections | Fail when the proportion is excessive |

This is why `expected_items` is not stored: **the index table reports the Items directly for each year.**

**Return problems as a list, not as exceptions.** A `raise` would stop at the first problem and hide the rest. The caller uses a single `if problems:` to decide whether relearning is necessary.

---

## 7. Output contract

<!-- src: app/ingestion/parser.py::SegmentType,ItemStatus,Block,Section,ParsedFiling -->
```python
SegmentType = Literal["number", "sec_canonical", "custom_title", "xref", "undefined"]
ItemStatus = Literal["parsed", "empty_disclosure", "incorporated_by_reference"]


@dataclass
class Block:
    kind: Literal["heading", "paragraph", "table"]
    text: str
    level: int | None = None  # 1=Item heading, 2=narrative subheading
    html: str | None = None  # raw table input for the M1.2 markdown converter
    source_pos: int | None = None  # start offset in the original HTML
    end_pos: int | None = None  # exclusive end offset in the original HTML
    source_group: int = 0  # contiguous narrative range within one Section
    source_heading: str | None = None  # title of that narrative range


@dataclass
class Section:
    part: str | None  # "I".."IV"
    item: str | None  # "1A"
    canonical_title: str  # SEC canonical title
    reported_title: str  # title used by the filing
    blocks: list[Block] = field(default_factory=list)
    status: ItemStatus = "parsed"
    reference_source: str | None = None
    # Location proves where an Item was found instead of merely claiming it was found.
    block_index: int | None = None  # heading block number
    block_range: tuple[int, int] | None = None  # block range occupied by this section
    source_pos: int | None = None  # character offset in the original HTML


@dataclass
class ParsedFiling:
    """Top-level output contract containing the complete parse of one filing."""

    doc_id: str  # "NVDA-FY2024"
    ticker: str
    cik: str
    form: str
    filing_date: str
    report_period: str
    fiscal_year: int
    accession: str
    source_url: str
    source_length: int = 0  # Unicode code points in the canonical decoded source
    source_sha256: str = ""  # SHA-256 of the exact source bytes
    sections: list[Section] = field(default_factory=list)
    item_index: list[dict] = field(default_factory=list)  # xref-only source index
    parse_status: str = "parsed"  # parsed | needs_profile_update
    warnings: list[str] = field(default_factory=list)
    profile_used: str = "saved"  # bootstrap | saved | relearned
    segment_type: str = ""
    # Validation measurements kept here so the CLI does not parse the filing twice.
    n_blocks: int = 0
    n_chars: int = 0  # total document text length, used as the coverage denominator
```

**The three location fields serve different purposes.**

| Field | Purpose |
|---|---|
| `block_index` | Internal parser debugging |
| `block_range` | Validation of the section boundary itself; input to the block range covered by a chunk in the M1.3_stage |
| `source_pos` | **Comparison against the source file.** Becomes the basis for **span citations** in the M1.3_stage (below) |

### Why `source_pos` became important — span citations

When citations point to a **chunk id**, changing chunking settings makes the referenced chunk disappear. That invalidates the entire golden set and makes **chunking ablation (quantifying "why this chunking?") impossible.**

When citations use **character offsets in the source**, they survive independently of chunking. Scoring uses **overlap (IoU)** with the gold span, so chunk boundaries do not need to match exactly either.

Therefore, during the M1.3_stage:

```
Block.source_pos / Block.end_pos   ← Section에만 있던 것을 Block까지 내린다
        ↓ 청크를 구성한 블록들의 (min, max)
Chunk.start_char / Chunk.end_char  ← 검색 결과의 인용 좌표
```

`source_pos()` and `line_offsets()` **already exist** ([L1](03-build.md)). Extending them to Block is L5 of the M1.3_stage. Keep the human-readable `citation` string ("NVDA FY2024 · Item 7"), while using the span alongside it as the **machine-evaluation coordinate** underneath.

**Why results contain `n_blocks`/`n_chars`** — the denominator for coverage validation is "all document text." Without these fields, the CLI reparses the document during every validation. Across the measured twenty files, the difference is forty seconds → eighteen seconds. **It is cheaper to return a measurement from the place that produced it.** ([B18](04-bugs.md#b18))

**Meaning of `status`** — a short section is usually a legitimate disclosure, not a bug. The source differs by type: the three title- or number-based types **infer** status from body text, while `xref` receives a **direct fact** from the index table. The latter preserves the source in `item_index`, supporting an evidence-backed answer such as "this Item is Not applicable."

**`Section.canonical_title` is independent of segment type.** For `sec_canonical`, every type still populates the field with the SEC standard title for that Item. The name is not `canonical_title`: `sec_canonical` means that *this title is used for matching*, and the distinction prevents that confusion.

---

## 8. Profile schema

`data/profiles/{TICKER}.json` — one file per company.

```json
{
  "ticker": "AMD",
  "default_year": "2023",
  "profiles": {
    "2019": {
      "segmentation": {
        "type": "number",
        "rules": [{ "font_weight": 700, "font_size": 10.0, "in_table": true }]
      },
      "validation": { "expected_items": 21, "must_have": ["1", "1A", "7", "8"] },
      "learned_from": "AMD-FY2019",
      "learned_by": "bootstrap",
      "learned_at": "2026-08-05T14:22:19+00:00"
    },
    "2023": {
      "segmentation": {
        "type": "number",
        "rules": [{ "font_weight": 700, "font_size": 10.0, "in_table": false }]
      },
      "validation": { "expected_items": 23, "must_have": ["1", "1A", "7", "8"] },
      "learned_from": "AMD-FY2023",
      "learned_by": "bootstrap",
      "learned_at": "2026-08-05T14:22:11+00:00"
    }
  }
}
```

The `2019` profile's `in_table: true` value is the trace left by [F4](01-findings.md#f4).

### Top-level fields

| Field | Meaning |
|---|---|
| `ticker` | Company |
| `default_year` | Year to use when the requested year is absent from `profiles`; **always the latest year** |
| `profiles` | Per-year profiles; **each entry is self-contained**, with no merge rule |

Why not use a `default` + override structure? It eliminates merge rules and naturally expresses how `validation.expected_items` varies by year (20~23 after the introduction of Item 1C). **This is an example of schema design directly determining code complexity**: `load_profile` takes only three lines.

### Profile fields

| Field | Meaning | Populated? |
|---|---|---|
| `segmentation` | Method for finding Item boundaries; a tagged union (below) | ✅ |
| `validation` | Criteria for validating parsed results | ✅ |
| `learned_from` | Document from which the profile was learned | ✅ |
| `learned_by` | `bootstrap` / `llm` / `manual` | ✅ (currently always `bootstrap`) |
| `learned_at` | Learning timestamp | ✅ |
| `evidence` | Measurements supporting classification | **✗ not populated** — design only |
| `description` | One human-readable line | **✗ not populated** — design only |

`evidence` and `description` are good ideas for making a file prove why it has a given type, but `build_profile` does not populate them yet. They are absent from the real `data/profiles/*.json` files.

### `segmentation` — tagged union

`type` is the tag, and the remaining fields are that type's payload.

```json
{ "type": "number",        "rules": [ ... ] }
{ "type": "sec_canonical", "rules": [ ... ] }
{ "type": "custom_title",  "rules": [ ... ], "order": [ {"item": "1A", "title": "Our Risk Landscape"} ] }
{ "type": "xref" }
{ "type": "undefined" }
```

**There are no optional fields.** `order` is required payload for `custom_title` and does not exist for other types. Likewise, `rules` is absent from `xref` and `undefined`.

Separate validation rules such as "rules are forbidden for `xref`" and "`order` is allowed only here" are therefore unnecessary. **The schema itself is the rule**, making invalid combinations unrepresentable.

Why not combine `sec_canonical` and `custom_title` into one type with an optional `order`? **Different actors populate the payload.** The first only needs comparison against a code constant, while the second cannot work without an externally constructed array. Combining them would make `order` optional and revive a conditional branch: "if present, do this; otherwise, do that."

---

## 9. Designed · not implemented ★

**This section is the boundary between documentation and code.** Some parts of the specification above exist only as designs. Mixing them together causes people to assume a feature exists in code and call it.

### Implementation status by type

`sec_canonical` and `custom_title` are **partially implemented, not wholly unimplemented**. Their segmentation paths exist in full; only their **detection (learning) functions are missing.**

| Type | Segmentation | Detection (learning) | Code |
|---|---|---|---|
| `number` | ✅ | ✅ | `parser.py` `detect_number` / `segment_by_heading` |
| `xref` | ✅ | ✅ | `parser.py` `detect_xref` / `segment_by_xref` + `xref.py` |
| `undefined` | ✅ (empty result) | ✅ (fallback) | `parser.py` `detect_segmentation` / `segment` |
| `sec_canonical` | ✅ `find_item` `case` | **✗ absent** | `match_canonical` exists but is **unreachable** |
| `custom_title` | ✅ `find_item` `case` | **✗ absent** | Nothing produces `order` |

`validate()` already contains the `custom_title` ordering branch based on `order`. **Parsing works as soon as the type can be established.** The only missing part is deciding "this document has that type."

### What does not exist

The following appeared in an earlier design document but **does not exist in code**. Calling any of it will fail.

| Name | Status |
|---|---|
| `detect_sec_canonical` / `detect_custom_title` | No such functions |
| `heading_candidates` / `derive_rules` | No such functions |
| LLM cascade ④ (`order` generation) · ⑤ (structure recognition) | Absent; `llm_profile.py` was deleted |
| CLI `--allow-llm` | No such flag |
| CLI `--disable <type>` | No such flag |
| CLI `--all` | No such flag (running without arguments already means all) |
| Profile `evidence` / `description` | Present in the schema, but not populated by `build_profile` |

The actual CLI has eight flags; see [L14 in 03-build.md](03-build.md).

### Added by later milestones

These fields and modules were foreshadowed in section seven and implemented by the M1.2 and M1.3_milestones. They were outside the original completion scope of the M1.1 parser but exist in the current code.

| Name | Status | Added in |
|---|---|---|
| `Block.source_pos` / `Block.end_pos` / `source_group` | ✅ implemented | [M1.3](../m1-3-chunk/02-spec.md) prerequisite |
| `Chunk.start_char` / `Chunk.end_char` | ✅ implemented | [M1.3](../m1-3-chunk/02-spec.md) L1/L5 |
| `tables.py` (table → markdown) | ✅ implemented | [M1.2](../m1-2-tables/02-spec.md) |

This is an **extension** that reuses `source_pos()` and `line_offsets()`. The `Block` code block has a source marker, so `check_doc_code.py --fix` refreshes it from the real code.

### Defined but not called

| Name | Status |
|---|---|
| `body_after()` | Defined with **no callers**; intended for `sec_canonical`/`custom_title` learning ([F12](01-findings.md#f12)) |
| `match_canonical()` | Called only by `find_item` in its `sec_canonical` branch → **unreachable** |
| `SegmentType` | Declared but **never used as an annotation**; `ParsedFiling.segment_type` is `str` |

`ItemStatus` is actually used by `Section.status`.

**Coverage confirms this independently.** Restricting the scope to the parser and xref modules and the ingestion suite as shown below concentrates uncovered lines in the dormant branches and CLI boundaries listed above. The documentation does not freeze line ranges and percentages that would become stale whenever the source changes.

```bash
uv run pytest --cov=app.ingestion.parser --cov=app.ingestion.xref --cov-report=term-missing tests/ingestion
```

In other words, **the claim "this code is unused" is verified by an executable measurement.** A repository-wide `--cov=app` figure mixes in M0/M4 code and the practice module `parser.py`, so it is not an appropriate criterion for M1.1.

### Why not build it now?

**There is no way to verify unreachable code built in advance.** This corpus reaches 20 filings out of twenty with `number` and `xref`, leaving no document that exercises the remaining paths.

Requirements for implementing them later:

- Disable `xref` detection and validate against Intel. Intel then becomes exactly the case targeted by `custom_title`: headings exist, but have neither numbers nor canonical titles.
- If an LLM participates, **④ and ⑤ must be mutually exclusive**: at most one per run.
- **Gate first.** Before anything else, verify that a batch run without the flag makes zero calls.
- **Code, not the LLM, constructs rules.** Ask "which lines are headings?" but not "what CSS rule covers those lines?" Code measures the actual properties of the selected lines and derives the rule.

### Experiment behind this conclusion

The final requirement is not speculation; it comes from an A/B benchmark. The same list of heading candidates from Intel's latest year was supplied to two prompts:

| | Prompt | LLM output |
|---|---|---|
| **A** | Title→Item mapping only | `title_map` |
| **B** | Deep analysis including style signatures | `heading_signals` + `title_map` + structural description |

**The additional `heading_signals` (= CSS rules) produced by B were frequently wrong.** The model mapped titles to Items well but could not independently derive a font rule that covered those titles. The current design therefore asks the LLM to do **only A**, while code derives the rules: [L9](03-build.md) uses `min()` to produce the loosest rule covering every observation.

> The experiment script `scripts/bench_llm_profile.py` was deleted. It was a one-off experiment that had answered its question, and it no longer ran because it depended on the removed `visual_sig`, the old `parse_filing(html, meta, profile)` signature, and the old profile schema (`strategy`/`heading_signals`/`title_map`). If needed, run `git show f06e59a:scripts/bench_llm_profile.py`.

The principle is **"the LLM operates only outside the boundary of measurement."** A stored profile governs five years of filings for a company, so **one misclassification becomes persistent.** By contrast, a measurement such as "twenty-three `Item N` blocks at weight seven hundred" cannot be wrong.

---

## 10. Design principles at a glance

| Principle | Implementation |
|---|---|
| Put rules in data, not code | `rules` live in profile JSON; adding a property requires only writing it into the profile |
| Put strategy selection in data too | One `segmentation.type` selects the parsing path |
| Start cheap; use expensive work only when failure is detected | Measurement (0.1seconds) → (unimplemented) LLM; graceful degradation |
| Do not discard state | Store classification failure as `undefined` to prevent repeated measurement |
| Do not save bad rules | Persist relearning **only after validation passes** |
| Treat year changes as facts, not exceptions | Independent `profiles` entries with no merge rule |
| Encode dependencies with tagged unions | `type` determines the payload, making invalid combinations unrepresentable |
| Fallback works only when failure is detectable | Four validation metrics ([F14](01-findings.md#f14)) |
