# M1.3 Findings

Before fixing the design, we exhaustively inspected the Blocks, source coordinates, and table Markdown across twenty 10-K filings. `tests/chunk/golden.py` owns the machine-enforced baseline; this document explains the design rationale.

## F1. Every Block Span Can Be Mapped to Source Coordinates

The 51 thousand eight hundred seventy-nine body Blocks produced by the parser yielded the following results:

- Missing `source_pos`: 0
- Missing `end_pos`: 0
- Reversed spans: 0
- Duplicate start positions: 0

Instead of searching for strings again in BeautifulSoup output, the implementation uses original line offsets and the start of the next Block. Coordinates are Python Unicode code-point indexes obtained by decoding the UTF-8 source bytes without newline translation. `source_sha256` binds those coordinates to the exact snapshot they address.

## F2. Grouping Blocks Is More Appropriate Than Fixed-Length Text Splitting

Text Block lengths were p50 fifty-seven characters, p90 seven hundred five, p95 1 thousand, p99 1 thousand six hundred forty-five, and a maximum of 3 thousand seven hundred seventy-three.

- Never split within a paragraph.
- Group multiple paragraphs up to a configurable target size.
- Keep a paragraph intact as one chunk even when it exceeds the target.

The target length is a grouping preference, not a destructive limit.

## F3. An xref Item Can Contain Multiple Discontiguous Source Ranges

In Intel filings, a single SEC Item can own several discontiguous narrative ranges. Grouping them merely because they belong to the same `Section.blocks` causes the citation span to cover other Items omitted between those ranges. The first implementation produced twelve such overlaps.

Splitting contiguous ranges with `source_group` and preserving each range's title in `source_heading` reduced the overlap count to zero and prevented the previous range's title from leaking into the next range's context.

## F4. Splitting Tables Without Row-Level Provenance Produces False Citations

M1.2 Markdown lengths were p50 four hundred one characters, p90 1 thousand four hundred seven, p95 2 thousand two hundred twenty-one, p99 3 thousand six hundred fifty-one, and a maximum of 4 thousand one hundred twenty-nine. Only three tables exceeded the previous 4 thousand-character threshold, but attaching the full table HTML span to each split fragment would cite ranges of 47K–137K characters—far larger than the fragments themselves.

Therefore, M1.3_ maps **exactly one source table to exactly one chunk**. Row splitting is allowed only after an implementation can track source coordinates for each row.

## F5. Final Corpus Baseline

| Kind | Count |
|---|---:|
| text | 8,083 |
| table | 1,089 |
| total | 9,172 |

These counts do not identify the best retrieval quality; they are a regression baseline for detecting unintended chunking changes.

## F6. Synthetic Context Must Be Separate from the Source Body

Repeating the Item name and narrative title helps retrieval, but those strings may not appear verbatim in the cited source slice.

- `body`: Evidence derived from the source
- `context_header`: Synthetic context repeated for retrieval
- `content`: `context_header + body`, the indexing input

Round-trip verification evaluates only `body`; retrieval uses `content`.

## F7. Section Order Does Not Always Match Source Order

The xref parser may return Sections in SEC Item order. The final chunks must be stably sorted by `(start_char, end_char)` and assigned new ordinals so citation and output order match the source order.

## F8. The Default Text Target Is an Ablation Arm

`DEFAULT_TARGET_TEXT_CHARS` at 1 thousand two hundred characters is a starting point. M3 evaluates multiple configurations against the same source spans. Because citations use source coordinates rather than chunk IDs, changing the configuration does not require regenerating golden citations.
