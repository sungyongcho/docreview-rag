# DocReview RAG — Development Log

> A record of building a document-grounded RAG workflow for SEC/DART filings — parsing, retrieval, evaluation and deployment preparation, implemented directly rather than through a framework.
> My role was to define requirements, acceptance criteria and review standards; AI assisted with much of the implementation. I separate what I verified from what I have not.

## At a glance

- **What it is**: not a chatbot demo — an LLM/RAG review workflow with retrieval, citations, evaluation and execution records.
- **My role**: define scope and acceptance criteria, judge architecture and policy, verify results, direct and review AI work.
- **Stack**: Python · FastAPI · Pydantic · SQLAlchemy · PostgreSQL/pgvector · Docker Compose · pytest · Next/React web UI · Ollama (local models).
- **Core implementation**: HTML/XML parsing and table normalization, structure-aware chunking, hybrid retrieval (RRF), optional cross-encoder reranking, structured outputs with typed failures, golden-set retrieval evaluation, cost and request limits.
- **How it was run**: issue contracts (86 issues) and pull requests (126, 119 merged), module-mirror tests, real-PostgreSQL verification (`live_postgres`), and recorded run traces.
- **Boundary**: this is not a live production service. The deployment specification and procedure are fixed; final answer-quality review is still with the author.

## 1. Starting and learning

### Why this project, and why now

The goal was to apply RAG to documents where evidence matters — filings — while still learning the concept. In this domain, "where did this sentence come from" matters more than the answer, so retrieval, citation and evaluation could all be exercised end to end. It was also the right time to build a public project that directly demonstrates the LLM/RAG experience the market asks for.

After studying in parallel (LangChain basics, then a RAG course, parts of KodeKloud and freeCodeCamp, and a BM25 video), the work done by following lectures stayed on the `lecture-tuto` and `lecture2-tuto` branches. A note recorded along the way — that the copied code still did not feel fully mine — changed how I studied.

### Learning by rebuilding

I split the code into a finished branch (`new`) and an empty learning branch (`zero`), then rebuilt it line by line by hand. Moving from parsing, tables, chunking and DB loading into embeddings and vector/keyword search, I verified concepts through questions — ORM usage, how far embeddings must be understood, BM25 and IDF. After retrieval evaluation came reassembling, reviewing, fixing and testing.

That early learning history (the `new`/`zero`/`assemble` branches, 2026-06 ~ 09) is no longer reachable in the current git history — it survives in the `v1` archive branch under `archive/provenance/history.jsonl`, where the carried-over parts can be traced.

### 1-1. Parsing — API acquisition and HTML parsing

I deliberately implemented the SEC EDGAR and DART parsing stage myself. I had never read either document format directly, so I needed to understand their components — and that work made the next stage's boundary question (what should count as one chunk) visible on its own.

```text
SEC/DART API ──download──▶ manifest          (source artifacts identified by SHA-256)
                              │
                              ▼
                  HTML/XML normalize          (drop script/style/img, unwrap iXBRL)
                              │
                              ▼
                  leaf blocks                 heading / paragraph / table
                              │               + source character offsets (source_pos)
                              ▼
                  segment by section          SEC: Item headings · DART: SECTION/TITLE
                              │
                              ▼
                  ParsedFiling ──▶ chunking
```

The technique is **DOM text extraction with BeautifulSoup + html.parser (tag stripping)**. `script/style/noscript/img` are removed, the non-rendered iXBRL `ix:header` is dropped entirely, and other `ix:*` tags are unwrapped so their numbers survive. Source line and character offsets come from `html.parser`'s `sourceline/sourcepos`. No OCR, PDF or image parsing is used: images carry little of a filing's information, so the pipeline stays text- and table-centric.

**SEC segmentation** finds `Item N.` headings with font-weight and font-size heuristics. Styles differ per document, so the parser learns a profile per issuer (for example weight ≥ 700, size 10pt), stores successful profiles under `data/profiles/*.json`, and relearns on validation failure. Documents with no Item headings at all (Intel 2019+) fall back to joining SEC's Cross-Reference Index with the company table of contents by page ranges.

```text
HTML blocks
   │
   ├─ "Item 1A. Risk Factors" passes the learned style profile? ── yes ─▶ Section boundary
   │        (at least 5 hits; rejected if it looks like a table of contents)
   │
   └─ no Item headings at all (Intel 2019+) ──▶ XRef Index + TOC page join
                                                + second sweep to recover missing Items
```

**DART** needs no heuristics: the markup is read directly. `SECTION-1 > TITLE` gives the twelve top-level divisions (I–XII); coverage under 90% warns, and zero numbered divisions fail closed. For encoding, permissive declarations (e.g. ISO-8859-1) are not trusted; decoding uses a strict allow-list of `utf-8/utf-8-sig/cp949/euc-kr`.

**Table normalization** is its own pipeline. `rowspan/colspan` are expanded into a dense grid, empty rows and columns are dropped, unit columns (`$`, `%`, `₩`) are folded toward their values, headers are inferred from shape, and the result is serialized to Markdown. When no header can be found the table keeps an empty header — a data row is never promoted into one.

```table-normalize-demo
```

Negative values like `(1,234)` are preserved as written: a citation must match the filing the reader sees, and normalizing here is irreversible. Original cell spans and ownership are also kept in a separate structure so later splits can trace which source cell a value came from.

> **Why build the parser**: an off-the-shelf parser would have been faster, but it would also hide how Items, tables and paragraphs are separated — exactly what the next stages depend on. What parsing taught about structure became the basis for chunking and citation design.

### 1-2. Chunking — splitting that preserves structure

Chunking decides what counts as a searchable unit. Two rules governed it: never cross table, heading or paragraph boundaries, and keep every piece aligned to its original text.

| Parameter | Value | Why |
|---|---|---|
| target tokens | 2,048 | target size for an embedding input |
| max tokens | 8,192 | model input limit (fail/split instead of truncating) |
| max chars | 12,000 | character-based ceiling |
| overlap | none | span alignment and no duplicated citations |
| context header | citation + title + heading | remains meaningful when retrieved alone |

```chunk-map
```

Tables are packed by row first; if one row is too large, by cell; if a cell still does not fit, by sentence. Headers and unit captions are repeated in every fragment so values never lose context. A unit caption (`(unit: million KRW)`) is carried to the next table only, and dropped when it would leak elsewhere. Once an embedding provider is selected, the token budget is recomputed with that model's actual tokenizer and input limit.

> **Why no overlap**: citation accuracy came first. Overlapping pieces can cite the same sentence twice and blur span tracking. Context is instead restored with the header line built into each indexed chunk.

```chunk-demo
```

### 1-3. Embeddings — vectorization and dimensions

Embeddings turn text into vectors so retrieval can work on meaning. OpenAI `text-embedding-3-large` is used at **384 dimensions** (Matryoshka truncation), and the database schema pins 384 as a `Literal[384]` contract. The provider/model/dimension/tokenizer combination is stored as the vector identity, so a changed vector space never mixes silently — it becomes a re-embedding target.

```text
document chunk (index_text) ─┐
                             ├─ same provider · model · dimension ─▶ 384-d vector ─▶ pgvector
question (normalized)       ─┘        (embed_query = embed_documents([q])[0])
```

For tests and local work there is also a deterministic token-hash embedding (reproducible) and a local sentence-transformers (MiniLM) path. This is also where I learned how many models Hugging Face and similar services serve.

> **The reason for 384 is not recorded.** It was not chosen from measured quality or storage trade-offs, so the log keeps it as a fixed contract. Truncating a large model is a real trade-off (quality vs storage/latency), but it is not a measured result.

### 1-4. Keyword indexing and hybrid retrieval

Keyword search catches proper nouns, numbers and phrases that vector search can miss. The default lexical ranker is PostgreSQL `ts_rank_cd` (cover density); BM25 is implemented separately as an optional ranker and compared against it.

**Korean** was the hard problem here. The `english` configuration cannot break Korean into meaningful terms, and agglutinative variants diverge. Korean rows are therefore indexed as overlapping character bigrams under `simple`, and the query is transformed by the same function. The measurements recorded in the code (24 positive DART FY2024 cases) were:

| Korean lexical ranker | hit_rate@5 | MRR@5 |
|---|---|---|
| BM25 · bigram | 0.875 | 0.684 |
| BM25 · trigram | 0.792 | 0.649 |
| BM25 · whitespace | 0.792 | 0.653 |
| ts_rank_cd (all variants) | 0.33–0.42 | — |

**BM25** is computed in SQL over per-language statistics tables (`chunk_terms`, `chunk_lengths`, `lexeme_stats`, `bm25_corpus_stats`).

$$
\begin{aligned}
\mathrm{idf}_{\mathrm{lucene}} &= \ln\!\left(1 + \frac{N - df + 0.5}{df + 0.5}\right)\\
\mathrm{length\_norm} &= 1 - b + b \cdot \frac{dl}{\overline{dl}}\\
\mathrm{saturation} &= \frac{tf \cdot (k_1 + 1)}{tf + k_1 \cdot \mathrm{length\_norm}}\\
\mathrm{score} &= \sum_{t} \mathrm{idf}_t \cdot \mathrm{saturation}_t \qquad (k_1 = 1.2,\; b = 0.75)
\end{aligned}
$$

```bm25-demo
```

The most memorable part was the shape of the formula. **Logging IDF makes common terms drop out of the score, and tf saturation puts a ceiling on the benefit of repeating a word.** Filings are full of words like "company" and "financial" that appear in almost every document — the logarithm lets them quietly drop out, while a rare issuer name or a term like "convertible debt" decides the ranking. A document repeating one keyword ten times stops gaining at the ceiling, so a document covering several query terms wins instead. The score ends up measuring how specifically a document covers the question, not how often words appear — the mini-lab above shows this directly. The same scoring also runs with Robertson IDF, and stale statistics make the search fail loudly instead of ranking wrongly in silence (a chunk-change trigger invalidates the stats and calls for a rebuild).

**Hybrid fusion** is rank-only RRF. Scores are never added directly; only ranks are summed.

```text
vector lane : A(1)  B(2)  C(3)
lexical lane: B(1)  D(2)  A(3)
```

$$
\mathrm{RRF}(d) = \sum_{\ell}\, \frac{1}{k + \mathrm{rank}_{\ell}(d)}, \qquad
\mathrm{A} = \tfrac{1}{60+1} + \tfrac{1}{60+3}, \qquad \mathrm{B} = \tfrac{1}{60+2} + \tfrac{1}{60+1}
$$

With k=60, only the first occurrence rank in each list counts.

```rrf-demo
```

```text
question ─┬─▶ vector search (pgvector cosine, exact scan) ─┐
          │                                                ├─▶ RRF ─▶ (optional) cross-encoder ─▶ top-k
          └─▶ lexical search (ts_rank_cd / BM25 / bigram) ─┘        ms-marco-MiniLM-L-6-v2
```

The candidate pool defaults to $\mathrm{candidate\_k} = \max(20,\, 4k)$, and the cross-encoder runs only for the Accuracy preset. No ANN index exists until measurements justify it; the exact scan favors reproducibility.

> **Why RRF**: vector and lexical scores live on different scales, and adding them lets one lane dominate. Rank-only fusion stays stable as lanes are added, at the cost of discarding score magnitude.

### 1-5. Answer models

During development I verified answers with `gpt-5.6-terra` and used Ollama locally for evaluation and tests. Because of deployment cost, the public service was fixed to `gpt-5.6-luna`; allowed models and prices are enforced as code policy (a model outside the policy is refused before any call). Development examples use terra; production accepts luna only.

Responses use strict JSON-schema decoding, with at most one repair attempt after a validation failure. When a call is projected to exceed budget it is refused before being sent. Local Ollama sets `num_ctx` explicitly so evidence cannot be silently truncated, and local engines are enabled only in DEV.

### 1-6. Evaluation and run records

To avoid judging retrieval by feel, I built a golden dataset and an evaluation framework. A gold span is pinned to the source location (`doc_id + sha256 + start/end`), and span coverage of at least 0.5 counts as a hit.

$$
\begin{aligned}
\mathrm{span\_coverage} &= \frac{|\mathrm{overlap}|}{|\mathrm{gold\ span}|}\\
\mathrm{recall@}k &= \frac{\text{hit gold spans}}{\text{gold spans}}\\
\mathrm{hit\_rate@}k &= \mathbf{1}\big[\text{top-}k\text{ contains a hit}\big]\\
\mathrm{RR} &= \frac{1}{\text{first hit rank}}, \qquad \mathrm{MRR} = \mathrm{mean}(\mathrm{RR})
\end{aligned}
$$

Coverage is 0 when the document or source digest differs; each metric is computed per question, then macro-averaged.

```eval-demo
```

Runs are split into `quick` (one evaluation against the current index) and `matrix` (isolated corpora × strategy/ranker/token combinations). Comparisons show metric deltas only when dataset, index and configuration fingerprints match; otherwise they are marked not comparable. Stage, elapsed time, tokens and failure cause are all recorded, and failures are typed as workflow budget / provider failure / node error.

### Actual development order (from records)

```pipeline-map
```

The items most easily missed are table normalization, the DART/Korean arm, the evaluation framework and cross-language parity, run tracing with failure typing, and answer-engine routing.

## 2. AI-assisted development loop: less repetition, same judgment

Previously I used AI through subscription services for code reading, concept learning and daily tasks. In this project I widened that by testing against benchmarks and examples myself. Understanding code and design still matters, but **when I state clearly what I already understand and give a precise example, handing over execution is incomparably faster**.

The routine settled into this shape.

- Describe the detailed plan first.
- Take a draft and narrow it through conversation.
  - Design: write a plan, review and revise it, then execute
  - UI: keep a live demo open and send instructions that apply immediately
  - Everything else: adjust to the purpose

Handing everything to AI is still risky. There is waiting time and cost, and results are not always satisfying. What did not happen was debugging taking longer and making the work less efficient.

### Where it helped most

- **Questions and evaluation sets**: generating English and Korean questions that fit the dataset, discussing which questions suit the parsed documents, and preparing test sets from those discussions.
- **Test code**: generating and updating tests with the implementation, keeping the module-mirror layout (`app/X/y.py` → `tests/X/test_y.py`). Ingestion, retrieval, workflow, evaluation and API-contract tests are separated, and schema checks that need a real database stay behind the `live_postgres` marker running against an isolated PostgreSQL.
- **Public API limit design**: 2 requests/minute and 5 per 24 hours per IP, $0.005 per call, $0.10 daily UTC reservation cap. Both embedding and answer calls reserve against the cap immediately before the real call, coordinated atomically through a persistent SQLite ledger (single host). SDK automatic retries are disabled so the cap cannot be bypassed.
- **Cloud cost estimates**: e2-medium on demand about $0.034/h (≈ $25/month) plus about $1 for the 30 GB disk ≈ $26/month. Ephemeral IP free (+$3 if reserved), Firebase and Cloudflare free tiers, and a $0.10 daily OpenAI cap. Committed use or spot pricing can lower this.
- **Failure diagnosis design**: a taxonomy that separates workflow budget, provider failure and node error. Making "which resource blocked this" reproducible mattered as much as adding features.

### Improvements

- Discussing implementation made it fast to survey other approaches; information gathering clearly accelerated.
- On UI, I kept looking at the running screen, removed features, and focused on the flow. The criterion was how easily a user reaches the goal after landing.
- Code lookup and error response got faster. Requests like "remove this code and clean up the compatibility and legacy code left behind" or "compare the previous evaluation results for this company and explain why this error happened" could be handled immediately.

### Limits and response

Waiting, cost and dissatisfaction were real. To reduce them I built and am improving an **internal workflow that fixes scope as an issue contract, isolates the workspace, preserves verification evidence, and records handoffs and review state**. Live sessions for immediate feedback belong to the same idea. As a result this project ran as 86 issues and 126 pull requests (119 merged), and it became possible to re-check later why something ended up as it did. Token usage remains a real cost.

This project is also an **experiment in improving the development process itself** — deciding what unit of work to split and what evidence to leave behind, rather than only using tools.

## 3. Deployment and wrap-up

### Deployment environment (confirmed specification, estimated cost)

| Item | Detail | Cost |
|---|---|---|
| GCP e2-medium | 2 shared vCPU, 4 GB RAM + 2 GB swap, 30 GB pd-standard | ≈ $25/month |
| Boot disk | 30 GB `pd-standard` | ≈ $1/month |
| External IP | Ephemeral (+$3 if reserved) | $0 |
| Static site | Firebase Hosting (static export) | $0 |
| Routing | Cloudflare Worker (shared with the gomoku Worker) | $0 |
| OpenAI | $0.10 daily cap | ≤ $0.10/day |

| Embedding model | Input | Output |
|---|---|---|
| `text-embedding-3-large` | $0.13 / 1M tokens | $0 |

> Note: whether the static site stays on Firebase or is served from the same e2-medium through Caddy is not decided yet. There is no cost difference; this table will be updated once decided.

### PROD / DEV difference

- **PROD**: a corpus already parsed, chunked and embedded is loaded in the database; visitors get public read, search, answers and published snapshots. Admin features and local engines are disabled.
- **DEV**: the full pipeline (acquisition, parsing, chunking, embeddings, evaluation) runs, with the admin surface and local model connections available.

### Remaining work and limits

- Actual cloud deployment and public operation have not happened yet. This document records the confirmed specification and procedure.
- Final answer-quality review (author acceptance) and a wider sweep of hyperparameters and alternative algorithms were left for later; instead I chose to leave a reproducible evaluation framework and run records.
- Live user traffic, incident response and measured operating cost are post-deployment work.

### What I took away

- I did not use a framework because I wanted to understand RAG directly through this project. I studied LangChain/LangGraph through tutorials but chose to implement core RAG and the workflow myself, so that nothing important stayed hidden behind abstractions.
- A RAG pipeline looks simple as a concept: split documents, vectorize them, search with a question, hand the result to a model. **Improving performance and deploying it is a different problem.** Tuning the pipeline, algorithms and hyperparameters one by one shows why it gets complex. Building the retrieval-generation loop myself also led me to think about agentic flows — tool calls and state.
- Ultimately, **quality is decided by data — parsing, chunking, evaluation sets — more than by swapping models**. What AI shortened was the typing of implementations and tests; deciding what counts as correct — how to restore tables, how to index Korean queries, what belongs in the golden set — still needed my judgment. That is why most of the schedule went into table parsing, Korean retrieval, goldens and cross-language parity.
- I learned a great deal about using AI. Judgment and approval stay with me; repetition and execution go with AI. Unknown and difficult things have become areas I can solve by finding a way.

## References

- [LangChain basics course](https://www.inflearn.com/course/입문자를위한-랭체인-기초) — completed.
- [Retrieval Augmented Generation (RAG)](https://www.coursera.org/learn/retrieval-augmented-generation-rag) — modules covered.
- [KodeKloud RAG Crash Course](https://www.youtube.com/watch?v=swvzKSOEluc) — codebase structure review.
- [freeCodeCamp: Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8) — first 30 minutes.
- [BM25 study video](https://www.youtube.com/watch?v=ziiF1eFM3_4)
- [Gomoku Minimax/AlphaZero documentation](https://sungyongcho.com/gomoku/docs) — development-log structure reference.
