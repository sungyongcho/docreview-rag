# M8 Findings — What the system does with a Korean question

The M8 slot previously held the bilingual documentation-parity module; that gate survives as authoring infrastructure and the module number now carries the cross-lingual query path, which is where the original scope note put it. Everything below is read off committed code and committed evaluation artifacts, not inferred.

## F1 — The lexical arm is hard-wired to English at both ends

The chunk table computes its search vector with one fixed text-search configuration, and the query side names the same one:

```python
content_tsv: Mapped[str] = mapped_column(
    TSVECTOR,
    Computed("to_tsvector('english', index_text)", persisted=True),
    nullable=False,
)
```

`app/db/models.py` builds the column, `app/retrieval/lexical.py` holds `TEXT_SEARCH_CONFIG = "english"` and passes it to `websearch_to_tsquery`, and `app/retrieval/bm25.py` inherits the same lexemes through the term statistics built from that column. There is no per-document language tag and no second configuration. A Korean question is therefore tokenized by an English stemmer, and the lexemes it produces have no counterpart in the index — except for the Latin fragments the question happens to carry.

This is not a bug in the sense of a mistake. It is the exact consequence of a decision M2 made on purpose for an English corpus, and it is the first thing the module has to measure rather than assume.

## F2 — Hybrid fusion collapses to the vector arm without saying so

`hybrid_search` fuses two ranked lists with reciprocal-rank fusion. RRF has no notion of a component that could not answer: a component that returns nothing simply contributes no scores, and the fused ranking equals the other component's ranking. So a Korean query that produces no lexemes at all leaves the hybrid arm returning the vector arm's results under the hybrid label, at the cost of one extra database round trip. The measured run refines this: only 4 of 28 Korean questions collapse that cleanly. The other 24 pull an average of 16.82 candidates out of the English index on their Latin fragments and score `0.000000` recall, so the usual Korean failure is not a component that fell silent but a component that voted confidently for the wrong chunks. Both shapes are recorded in [verification](05-verify.md).

The failure is silent by construction. The caller receives a `RetrievalResult` with hits, a strategy name, and component rankings, and nothing in that payload says "one component was structurally unable to contribute". The only way to see it is to look at `ComponentRankings.lexical` and notice it is empty — which is exactly the observation M8.3 turns into a routing decision.

## F3 — Every committed vector number came from token-hash vectors

The committed ten-arm experiment in [the evaluation report](../eval-report.md) ran with `provider=deterministic`, whose vectors are token hashes rather than a semantic embedding. Its vector arms measured Recall@5 `0.125000` at chunk target 500 and `0.062500` at chunk target 1200 — noise floor, and honestly labelled as such in that report.

That caveat is decisive here. If the lexical arm is dead for Korean and the vector arm's only measured numbers are noise, then the question "does a Korean question find the right passage?" has no answer in this repository at all: one arm cannot answer and the other has never been measured with a real embedding space. The module's first deliverable is therefore not a fix. It is a measurement.

## F4 — Two 384-dimension providers make the vector arm testable without a migration

`app/db/models.py` pins `Vector(384)` and `app/config.py` pins `embed_dim: Literal[384]`, so any provider swap has to land in 384 dimensions or become a schema migration. Three candidates matter:

| Provider | Model | 384 dimensions | Cross-lingual |
|---|---|---|---|
| `openai` | `text-embedding-3-small` | truncated from 1536 via `dimensions=384` | multilingual, but measured here only in its truncated slice |
| `sbert` | `all-MiniLM-L6-v2` | native | English-only training data |
| `sbert` | `paraphrase-multilingual-MiniLM-L12-v2` | native | multilingual by design |

The multilingual sentence-transformer is native 384, so it drops into `Settings.sbert_model` with no schema change at all — the difference is entirely in the space the vectors live in. That matters twice: it makes a real cross-lingual vector arm reachable offline and free, and it gives the truncated OpenAI arm a co-equal comparison, so a weak OpenAI number can be attributed to Matryoshka truncation rather than to the model.

## F5 — The golden loader forbids twins in one batch

`load_golden_cases` accepts a file or a directory, and `_validate_unique_cases` rejects duplicate case ids, duplicate normalized questions, and duplicate answer-span identities across every case in one loaded batch. A Korean twin shares its answer span with its English original by design — that shared span is the whole point — so the two suites cannot be loaded together.

The consequence is a design constraint, not a workaround: the Korean cases live in their own file, `data/golden/retrieval_ko.json`, and are loaded by a second `load_golden_cases` call. Both files then get the loader's full SHA-256 and span-source verification for free, `data/golden/retrieval.json` stays byte-identical to what M3 froze, and the frozen `CASE_COUNT` contract in `tests/evals/test_02_loader.py` keeps holding.

## F6 — The headroom this module deliberately does not take

The scope note has always placed cross-lingual retrieval and a Korean-language source adapter in the same requirement — see section 8 of [the scope and narrative plan](../../project/planning/03-scope-and-narrative.md), which states the principle that only the parser entrance gets a per-source adapter while chunking, embedding, retrieval, and evaluation stay shared. A DART corpus is a second-round extension of exactly this design: a source adapter at the parser entrance, a per-document language tag, and a Korean text-search configuration for the lexical column, with the twin-suite pattern reversed so English questions are asked of Korean filings. The parity gate built in M8.4 becomes that corpus's acceptance gate without changing shape.

Two things are named as headroom and left undone. Korean-language *answers* to Korean questions are one prompt line away in the M4 workflow and have no deterministic metric in this repository — there is no LLM judge here, so answer-language fidelity could only be claimed, not measured, and the module's whole thesis is that claims are numbers. A Korean text-search configuration for the lexical column is a schema change with its own analyzer choice, and it is meaningless until there is Korean text in the corpus to index.
