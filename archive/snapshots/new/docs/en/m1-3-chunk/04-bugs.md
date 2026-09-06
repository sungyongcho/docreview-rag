# M1.3 Bugs

## B01. Using Chunk IDs for Citations Breaks Labels During Ablation

Changing the chunk target shifts every ordinal. The fix is to use `(doc_id, source_sha256, start_char, end_char)` as the persistent coordinates and treat the ordinal only as an ordering value for the current materialization.

## B02. Offsets Found in BeautifulSoup Output Are Not Source Coordinates

BeautifulSoup normalizes attribute order, entities, and whitespace. The fix is to decode the exact source bytes directly, derive the start from parser line offsets, and use the next Block start as the exclusive end. A fixture containing CRLF and Unicode locks down the coordinate semantics.

## B03. Preserving xref Section Order Breaks Source Order

The xref parser may return Sections in SEC Item order. The completed chunks are stably sorted by span and assigned new dense ordinals.

## B04. Discontiguous Ranges for One Item Were Grouped into One Chunk

In an Intel xref filing, another Item appeared between two ranges belonging to the same Item. Flushing the text buffer whenever `source_group` changes reduced the corpus overlap count from twelve to zero.

## B05. A Previous Narrative Title Leaked into the Next xref Range

Flushing only the text buffer while retaining context state leaves the previous heading in the next range's retrieval context. Each Block stores `source_heading`, and both the buffer and context are reset on a source-group transition. The canonical Item title takes precedence over `reported_title`, which combines multiple ranges.

## B06. Split Table Rows All Cited the Entire Table

The split body contained only part of a table, while its citation covered the entire 47K–137K-character table HTML. That architecture cannot claim exact provenance. Table splitting was removed until row-level source coordinates are available, establishing a 1-to-one mapping between source tables and table chunks.

## B07. Mixing Synthetic Context into the Body Causes False Round-Trip Failures

Repeated Item and title context may not exist in the source slice. Separating `context_header`, `body`, and `content` lets round-trip verification use the body while indexing uses the content.

## B08. Using Only Minimum and Maximum Values Without Validating Each Block Hides Invalid Spans

Even when the overall minimum and maximum values appear valid, an internal Block may be reversed, overlapping, in another group, or outside the document bounds. `_source_span()` now validates every Block in order before returning only the first start and final end.

## B09. Full-Table Token Equality Rejects Valid Header Merging

M1.2 multi-row headers are merged by column, so their order may differ from the source's global row-major order. Headers are verified by token-multiset containment and data rows by ordered subsequence.

## B10. Checking Only Some Chunks Misses Omissions and Duplicates

An exact-once regression test now verifies not only each chunk's round trip but also that every non-heading source body Block is contained in exactly one chunk span.
