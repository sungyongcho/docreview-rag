<!-- heading-alias: docreview-rag-development-log -->
# DocReview RAG — Development Log {#development-log}

> A record of building a document-grounded RAG workflow for SEC/DART filings — parsing, retrieval, evaluation and deployment preparation, implemented directly rather than through a framework.
> My role was to define requirements, acceptance criteria and review standards; AI assisted with much of the implementation. I separate what I verified from what I have not.

## At a glance {#at-a-glance}

- **What it is**: not a chatbot demo — an LLM/RAG review workflow with retrieval, citations, evaluation and execution records.
- **My role**: define scope and acceptance criteria, judge architecture and policy, verify results, direct and review AI work.
- **Stack**: Python · FastAPI · Pydantic · SQLAlchemy · PostgreSQL/pgvector · Docker Compose · pytest · Next/React web UI · Ollama (local models).
- **Core implementation**: HTML/XML parsing and table normalization, structure-aware chunking, hybrid retrieval (RRF), optional cross-encoder reranking, structured outputs with typed failures, golden-set retrieval evaluation, cost and request limits.
- **Verification**: module-level regression tests, real PostgreSQL checks, and inspection of recorded runs.
- **Boundary**: this is not a live production service. The deployment specification and procedure are fixed; final answer-quality review is still with the author.

<!-- heading-alias: 1-starting-and-learning -->
## 1. Starting and learning {#learning}

<!-- heading-alias: why-this-project-and-why-now -->
### Why this project, and why now {#motivation}

I wanted to turn an introductory understanding of RAG into a working system grounded in real documents. Filings made that goal concrete: **which source passage supports a claim** matters, bringing retrieval, citation and verification into the same project.

### From following examples to understanding the system {#learning-by-rebuilding}

Completing the course examples did not yet mean I could explain why each stage was needed. Rebuilding the core flow helped me examine one decision at a time: how to split a document, when embeddings remain reusable, and what a retrieval score measures.

From there, the work became a cycle of inspecting retrieval results, making changes and testing their effects. The sections below focus on the principles and design choices I learned through that process.

<!-- heading-alias: 1-1-parsing-api-acquisition-and-html-parsing -->
### 1-1. Parsing — API acquisition and HTML parsing {#parsing}

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

<!-- heading-alias: 1-2-chunking-splitting-that-preserves-structure -->
### 1-2. Chunking — splitting that preserves structure {#chunking}

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

<!-- heading-alias: 1-3-embeddings-vectorization-and-dimensions -->
### 1-3. Embeddings — vectorization and dimensions {#embeddings}

Embeddings turn text into vectors so retrieval can work on meaning. Requests to OpenAI `text-embedding-3-large` explicitly set **`dimensions=384`** for shortened vectors (Matryoshka-style dimension reduction), and the configuration and database vector width are also set to 384. The provider/model/dimension/tokenizer combination is stored as the vector identity, so a changed vector space never mixes silently — it becomes a re-embedding target.

```text
document chunk (index_text) ─┐
                             ├─ same provider · model · dimension ─▶ 384-d vector ─▶ pgvector
question (normalized)       ─┘        (embed_query = embed_documents([q])[0])
```

**Why this works as retrieval.** The question and each chunk are encoded independently into one shared vector space — a bi-encoder-style pattern — so search becomes a comparison between vectors, here pgvector cosine similarity. Independence is what makes precomputation possible: chunk vectors are stored once and stay reusable while the chunk text and the embedding identity/configuration remain compatible, while a query is embedded only when a request arrives — and a translated query variant gets its own embedding. The two encoding roles may share one set of weights; the pattern does not require two separate model instances. This describes the retrieval architecture, not a proprietary provider's internals.

For tests and local work there is also a deterministic token-hash embedding (reproducible) and a local sentence-transformers (MiniLM) path. This is also where I learned how many models Hugging Face and similar services serve.

**Dimensions define the size of a vector representing a text's meaning.** They count the numbers in each vector, and the default output size varies by model. The local `all-MiniLM-L6-v2` model produces 384 dimensions, while `text-embedding-3-large` defaults to 3072. This project shortens the OpenAI model's output to 384 dimensions. [Sentence Transformers example](https://www.sbert.net/docs/quickstart.html), [OpenAI embedding documentation](https://developers.openai.com/api/docs/guides/embeddings)

[Matryoshka training](https://www.sbert.net/examples/sentence_transformer/training/matryoshka/README.html) trains both the full vector and smaller prefixes to remain useful, allowing semantic representations to be used at smaller sizes. The project requests its desired dimension through OpenAI's supported shortening API; arbitrary truncation of other models does not imply the same property.

Reducing 3072 to 384 leaves one eighth as many components to store and compare. Using [pgvector's storage formula](https://github.com/pgvector/pgvector#vector-type), `4 × dimensions + 8`, one vector value shrinks from 12,296 to 1,544 bytes. Total storage and response time also depend on indexing, model calls and other factors. [OpenAI API charges are based on input tokens](https://developers.openai.com/api/docs/guides/embeddings), independently of output dimension reduction.

**The current document scope uses 384 dimensions.** Growth in corpus size or topic diversity, or a need for finer semantic distinctions, could justify evaluating larger vectors against retrieval quality and latency. The current corpus is relatively small and consists of filings with consistent report formats and section structures. Having verified the retrieval and answer flow within that scope, I retained 384 dimensions for the current configuration.

<!-- heading-alias: 1-4-keyword-indexing-and-hybrid-retrieval -->
### 1-4. Keyword indexing and hybrid retrieval {#retrieval}

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

What stayed with me was how the formula handles repetition. **IDF reduces the weight of common terms; tf saturation limits the benefit of repeating one word.** An issuer name or a rare term can therefore distinguish filings better than words such as "company" or "financial". The score reflects distinctive coverage of the question, rather than occurrence counts alone. Change k1 and b in the mini-lab above to see the difference.

The implementation also supports Robertson IDF. When chunks change and statistics become stale, retrieval stops and requests a rebuild. I chose an explicit request to refresh the index over plausible rankings calculated from outdated statistics.

**Hybrid fusion** is rank-based score fusion (RRF): each lane's rank contributes a reciprocal-rank term — raw vector/lexical scores and raw rank numbers are never summed directly. Computing A and B from the two lanes in the mini-lab below:

$$
\mathrm{RRF}(d) = \sum_{\ell}\, \frac{1}{k + \mathrm{rank}_{\ell}(d)}, \qquad
\mathrm{A} = \tfrac{1}{60+1} + \tfrac{1}{60+3}, \qquad \mathrm{B} = \tfrac{1}{60+2} + \tfrac{1}{60+1}
$$

The k=60 here is the smoothing constant `rrf_k` — distinct from the k=5 hits eventually returned. A document contributes only its first-occurrence rank in each list.

```rrf-demo
```

```text
question ─┬─▶ vector search (pgvector cosine, exact scan) ─┐
          │                                                ├─▶ RRF (rank-based score fusion)
          └─▶ lexical search (ts_rank_cd / BM25 / bigram) ─┘            │
                                                              fused candidate pool (≤ candidate_k)
                                                                          │
                                                          (optional) cross-encoder
                                                          ms-marco-MiniLM-L-6-v2
                                                          scores each (question,
                                                          passage) pair
                                                                          │
                                                                          ▼
                                                final top-k ─▶ answer and citation checks
```

The candidate pool defaults to $\mathrm{candidate\_k} = \max(20,\, 4k)$, and the cross-encoder runs only for the Accuracy preset. No ANN index exists until measurements justify it; the exact scan favors reproducibility.

**What the optional reranker does.** The two lanes propose candidates and RRF fuses their ranks into a bounded pool. Reranking is the operation of reordering that already-retrieved pool — here performed by a cross-encoder, which is the chosen model for the job, not a synonym for reranking itself. A cross-encoder reads one (question, passage) pair jointly and produces a relevance score, so it can model token interactions directly: a keyword-dense passage about a different relationship can rank below a passage that addresses the asked relationship — a qualitative illustration, not a measurement. It scores text pairs rather than stored vectors, so toggling it never requires re-embedding the corpus, and it cannot recover evidence that never entered the pool.

**What it scores.** The reranker scores the whole fused pool — never every corpus chunk, and not only the five hits that will be returned. The built-in presets make this concrete: Balanced is k=5 / candidate_k=20 / no reranker, Korean is k=5 / candidate_k=30 / no reranker, and Accuracy is k=5 / candidate_k=50 / cross-encoder, so Accuracy can score up to 50 (question, passage) pairs before returning five hits. Pair scoring is batched local backend inference, not 50 separate network or API requests — first-use weight loading, weight caching, the query-embedding API call, and pair inference are distinct costs. More candidates and cross-encoding can add compute and latency, and quality still depends on domain, language and corpus fit — the preset name is no guarantee. Answer generation and citation validation run downstream of the final top-k.

> **Why RRF**: vector and lexical scores live on different scales, and adding them lets one lane dominate. Rank-only fusion stays stable as lanes are added, at the cost of discarding score magnitude.

<!-- heading-alias: 1-5-answer-models -->
### 1-5. Answer models {#answer-models}

During development I verified answers with `gpt-5.6-terra` and used Ollama locally for evaluation and tests. Because of deployment cost, the public service was fixed to `gpt-5.6-luna`; allowed models and prices are enforced as code policy (a model outside the policy is refused before any call). Development examples use terra; production accepts luna only.

Responses use strict JSON-schema decoding, with at most one repair attempt after a validation failure. When a call is projected to exceed budget it is refused before being sent. Local Ollama sets `num_ctx` explicitly so evidence cannot be silently truncated, and local engines are enabled only in DEV.

<!-- heading-alias: routing-before-retrieval -->
#### Routing before retrieval {#routing}

Valid JSON guarantees the response format. **Whether the request belongs to this service, and whether the required filings exist, are separate questions.** Before retrieval, stage 0 selects a route and stage 1 checks the server's provided document scope.

```routing-demo
```

Change the example or turn off prior conversation to compare retrieval, scope guidance and a pending classification. This is a fixed illustrative inventory; the experiment performs no search or model calls.

The starting point is **not asking a model to guess what server rules can already establish**. A fully covered request skips classification, reducing latency, cost and variance. But a request clear to a person may still fall outside the rules. Recognizing one company never justifies dropping an unknown company mentioned alongside it. The rules distinguish these cases:

- an analysis request whose targets are all known aliases routes to analysis;
- an exact greeting, thanks or usage question receives the fixed service guidance;
- a clearly out-of-scope request such as role-play receives the scope notice;
- an unambiguous follow-up keeps the route its bounded context points to.

A follow-up can reuse a bounded earlier user question that passes the rules. This is not proof that the earlier run succeeded. Only unresolved requests need model classification; a classification failure stays a technical error rather than becoming a free-form answer.

<!-- details: routing-call-records | What classifier calls and conversation records mean -->

There is one classification decision per request, but provider retries and schema repair can add call attempts. Each actual attempt is measured. The conversation schema stores role and text only: a prior question matching a rule is different from a prior request having succeeded.

Stage 1 checks aliases, companies, years and documents against the server-provided inventory instead of trusting the model's answer. A target the server cannot identify never broadens into an all-corpus search.

<!-- /details -->

The first is the **path decision**, stage 0 in the interface. It classifies a request as company, financial or filing analysis; bounded service guidance; or outside the service. A question about a company's growth or performance counts as analysis even when it never mentions SEC or DART, while greetings, thanks and usage questions receive fixed service guidance. General conversation or role-play such as "Talk to a cat" ends here with a service-scope notice instead of producing a free-form model answer. When the rules cannot settle a request, the classifier decision is made by a model call — so an early stop does not mean zero calls, and "no classifier call" does not mean "no model calls" either: for a request that proceeds, whether it embeds its query or calls the answer model depends on the retrieval mode and how far it gets. The run record keeps only the calls that actually happened.

The second is stage 1, **understand the question**. It identifies the requested companies, period and selected document scope, resolves supported aliases to companies represented in the available corpus, then checks the server's real provided corpus. A model can identify a company name in the question, but the server — not the model — verifies whether its filings are present. "SanDisk growth drivers" is a valid analysis intent and passes stage 0, yet it stops here because SanDisk is absent from the current corpus.

An unprovided company is neither a wrong question nor proof the company does not exist. Ambiguous names get a clarification request, and a missing company never broadens the search to every company or substitutes another. A supported alias such as NVIDIA can resolve to the NVDA company in the corpus, but appearing on a filing-acquisition candidate list alone does not mean filings are present. A requested year or selected scope that matches no provided filing also stops before search.

<!-- heading-alias: why-question-language-does-not-select-the-corpus -->
#### Why question language does not select the corpus {#language-and-scope}

An English question might seem to need only English filings. But "Compare Nvidia and Samsung revenue" needs NVIDIA's SEC filings and Samsung's Korean DART filings. Filtering by the question's language would remove Samsung before retrieval even starts. Translation or multilingual embeddings cannot recover evidence that the scope already excluded.

That is why question language and document scope are separate. With automatic scope and no additional restrictions, an all-company comparison includes both SEC and DART, whether asked in English or Korean. Selecting SEC explicitly limits the scope to SEC. Company, year, document selections and explicit document-language filters remain binding; the question's language alone cannot override them. Naming a DART company while SEC is selected produces a scope conflict instead of silently omitting that company or ignoring the selection.

This prevents a language shortcut from dropping a requested source, but it does not solve cross-language retrieval quality. A filing being in scope does not guarantee that retrieval finds the right passage or that the passage supports an answer. Change the two controls below to see the distinction: question language changes the wording; an explicit source selection changes which filings are eligible.

```scope-demo
```

#### Question and answer language {#answer-language}

**The default is to answer in the same language as the question.** A Korean question about NVIDIA should receive a Korean answer even when its evidence comes from English SEC filings. An English question about Samsung should receive an English answer even when the evidence is in Korean DART filings. A different response language is used only when the user explicitly requests one.

Separating search scope did not establish this rule by itself. Previously, the answer prompt had no language policy, and rewriting a follow-up for retrieval could obscure the original question's language. The server now preserves that question as `original_query` and passes it separately from the retrieval `query`. The system prompt for the existing evidence-grading and answer calls uses the original question as the language reference, without adding a language-classification call.

The rule applies to answers and explanations; verbatim quotations, company codes and verdict values such as `SUPPORTED` remain unchanged. When insufficient evidence stops generation or citation validation rejects an answer, the server's fixed notice also follows the original question's Korean or English language, without a model call. For mixed-language model answers, the instruction follows the request's language rather than a company name or quoted passage. Regression tests verify prompt delivery and preservation of language requests. They do not prove model compliance: this implementation does not separately validate output language or retry with a translation.

<!-- heading-alias: verdicts-and-records -->
#### Verdicts and records {#verdicts}

Only an accepted request with an available scope proceeds to evidence retrieval, relevance selection and answer/citation validation. For document-review requests that reached evidence evaluation, the verdict is `SUPPORTED` or `NOT_IN_DOCS`. `SUPPORTED` means the cited evidence passed verification — not just that the model claimed support — and the schema itself rejects a supported answer without citations. When citations the model asked for are filtered by validation, the whole report degrades to absence (`support_downgraded`) instead of shipping a partially cited answer. An absence verdict (`NOT_IN_DOCS`) is a different result from an operational failure (provider, node or budget).

One optional call remains inside retrieval itself: language-specific query rewriting is enabled separately, and when it runs it is recorded as a real call like any other.

Where a request ends decides which outcome is recorded.

| Where it ends | Outcome | Meaning |
|---|---|---|
| 0. Path decision | fixed or service-scope guidance | bounded service help or an unsupported purpose — not a document-review verdict |
| 1. Understand the question | scope guidance | unavailable or ambiguous company, year or scope — not `NOT_IN_DOCS` |
| Evidence review | `NOT_IN_DOCS` | a valid scope was searched but the evidence is insufficient |
| Evidence review | `SUPPORTED` | an answer whose citations passed verification |
| Any point | technical/operational failure | catalog lookup, provider, timeout or budget — never converted into guidance |

> **Why stop early**: an unconstrained LLM reply can read as more fluent and accommodating, but it bypasses the available evidence and makes the product's scope look wider than it is. Explicit early guidance is more limited and can ask the user to reformulate, yet it keeps grounding and execution history trustworthy. These decisions supplement the structured schemas and citation checks; they do not replace them.

The interface shows the stage and reason where a request actually stopped; stages that never ran are not recorded as failed checks or completed verification. Classifier and model calls that did occur count toward the call totals even on an early stop — including provider retries and the one schema-repair attempt, which are measured calls rather than free recovery. DEV and PROD share this rule — the environments differ in permissions, model choices and preparation controls, and PROD is not a separate permissive conversation product. Historical run records keep their original results.

<!-- heading-alias: 1-6-evaluation-and-run-records -->
### 1-6. Evaluation and run records {#evaluation}

To avoid judging retrieval by feel, I built a golden dataset and an evaluation framework. A gold span is pinned to the source location (`doc_id + sha256 + start/end`), and span coverage of at least 0.5 counts as a hit.

$$
\begin{aligned}
\mathrm{span\_coverage} &= \frac{|\mathrm{overlap}|}{|\mathrm{gold\ span}|}\\[0.8em]
\mathrm{recall@}k &= \frac{\text{hit gold spans}}{\text{gold spans}}\\[0.8em]
\mathrm{hit\_rate@}k &= \mathbf{1}\big[\text{top-}k\text{ contains a hit}\big]\\[0.8em]
\mathrm{RR} &= \frac{1}{\text{first hit rank}}\\[0.8em]
\mathrm{MRR} &= \mathrm{mean}(\mathrm{RR})
\end{aligned}
$$

Coverage is 0 when the document or source digest differs; each metric is computed per question, then macro-averaged.

```eval-demo
```

Runs are split into `quick` (one evaluation against the current index) and `matrix` (isolated corpora × strategy/ranker/token combinations). Comparisons show metric deltas only when dataset, index and configuration fingerprints match; otherwise they are marked not comparable. Stage, elapsed time, tokens and failure cause are all recorded, and failures are typed as workflow budget / provider failure / node error.

<!-- heading-alias: build-order-recap-from-records -->
### Build order recap (from records) {#build-order}

```pipeline-map
```

The items most easily missed are table normalization, the DART/Korean arm, the evaluation framework and cross-language parity, run tracing with failure typing, and answer-engine routing.

<!-- heading-alias: 2-ai-assisted-development-loop-less-repetition-same-judgment -->
## 2. AI-assisted development loop: less repetition, same judgment {#ai-collaboration}

Previously I used AI through subscription services for code reading, concept learning and daily tasks. In this project I widened that by testing against benchmarks and examples myself. Understanding code and design still matters, but **when I state clearly what I already understand and give a precise example, handing over execution is incomparably faster**.

The routine settled into this shape.

- Describe the detailed plan first.
- Take a draft and narrow it through conversation.
  - Design: write a plan, review and revise it, then execute
  - UI: keep a live demo open and send instructions that apply immediately
  - Everything else: adjust to the purpose

Handing everything to AI is still risky. There is waiting time and cost, and results are not always satisfying. What did not happen was debugging taking longer and making the work less efficient.

<!-- heading-alias: where-it-helped-most -->
### Where it helped most {#repetitive-work}

- **Questions and evaluation sets**: generating English and Korean questions that fit the dataset, discussing which questions suit the parsed documents, and preparing test sets from those discussions.
- **Test code**: generating and updating tests with the implementation, keeping the module-mirror layout (`app/X/y.py` → `tests/X/test_y.py`). Ingestion, retrieval, workflow, evaluation and API-contract tests are separated, and schema checks that need a real database stay behind the `live_postgres` marker running against an isolated PostgreSQL.
- **Public API limit design**: 10 requests/minute and 50 per 24 hours per IP, \$0.005 per call, \$0.10 daily UTC reservation cap. Both embedding and answer calls reserve against the cap immediately before the real call, coordinated atomically through a persistent SQLite ledger (single host). SDK automatic retries are disabled so the cap cannot be bypassed.
- **Cloud cost estimates**: e2-medium on demand about \$0.034/h (≈ \$25/month) plus about \$1 for the 30 GB disk ≈ \$26/month. Ephemeral IP free (+\$3 if reserved), Firebase and Cloudflare free tiers, and a \$0.10 daily OpenAI cap. Committed use or spot pricing can lower this.
- **Failure diagnosis design**: a taxonomy that separates workflow budget, provider failure and node error. Making "which resource blocked this" reproducible mattered as much as adding features.

### Improvements {#improvements}

- Discussing implementation made it fast to survey other approaches; information gathering clearly accelerated.
- Using AI reduced the time spent on repetitive implementation and testing, and I invested much of that freed-up time in refining the user experience. I am still developing a feel for visual polish and UI design, so I focused on making sure a user understands what to do and can carry a task through to the end. Using the screens myself, I repeatedly checked and improved whether the next step was clear, whether settings and run results were understandable, and whether a way forward existed when something went wrong.
- Code lookup and error response got faster. Requests like "remove this code and clean up the compatibility and legacy code left behind" or "compare the previous evaluation results for this company and explain why this error happened" could be handled immediately.

<!-- heading-alias: limits-and-response -->
### Limits and response {#tradeoffs}

Waiting, cost and dissatisfaction were real. To manage them, I built and continue to improve a workflow that **sets a clear goal and verification method, separates working areas, and preserves the context needed for the next task**. I also used live feedback while inspecting the interface. This helped carry requirements and test results through repeated revisions, although token usage and waiting time remain costs to manage.

This project is also an **experiment in improving the development process itself** — deciding what unit of work to split and what evidence to leave behind, rather than only using tools.

<!-- heading-alias: 3-deployment-and-wrap-up -->
## 3. Deployment and wrap-up {#deployment}

<!-- heading-alias: deployment-environment-confirmed-specification-estimated-cost -->
### Deployment environment (confirmed specification, estimated cost) {#deployment-environment}

| Item | Detail | Cost |
|---|---|---|
| GCP e2-medium | 2 shared vCPU, 4 GB RAM + 2 GB swap, 30 GB pd-standard | ≈ \$25/month |
| Boot disk | 30 GB `pd-standard` | ≈ \$1/month |
| External IP | Ephemeral (+\$3 if reserved) | \$0 |
| Static site | Next.js static export → Firebase Hosting | \$0 |
| Routing | Cloudflare Worker → Firebase / GCP Caddy | \$0 |
| OpenAI | \$0.10 daily cap | ≤ \$0.10/day |

| Embedding model | Input | Output |
|---|---|---|
| `text-embedding-3-large` | \$0.13 / 1M tokens | \$0 |

The static site runs on **Firebase Hosting**, while the API and database run on **GCP e2-medium**. The Cloudflare Worker routes requests between these services by path, and Caddy on the VM proxies API requests to FastAPI.

<!-- heading-alias: prod-dev-difference -->
### PROD / DEV difference {#runtime-modes}

- **PROD**: a corpus already parsed, chunked and embedded is loaded in the database; visitors get public read, search, answers and published snapshots. Admin features and local engines are disabled.
- **DEV**: the full pipeline (acquisition, parsing, chunking, embeddings, evaluation) runs, with the admin surface and local model connections available.

<!-- heading-alias: remaining-work-and-limits -->
### Remaining work and limits {#remaining-work}

- Actual cloud deployment and public operation have not happened yet. This document records the confirmed specification and procedure.
- Final answer-quality review (author acceptance) and a wider sweep of hyperparameters and alternative algorithms were left for later; instead I chose to leave a reproducible evaluation framework and run records.
- Live user traffic, incident response and measured operating cost are post-deployment work.

<!-- heading-alias: what-i-took-away -->
### What I took away {#reflections}

- I did not use a framework because I wanted to understand RAG directly through this project. I studied LangChain/LangGraph through tutorials but chose to implement core RAG and the workflow myself, so that nothing important stayed hidden behind abstractions.
- A RAG pipeline looks simple as a concept: split documents, vectorize them, search with a question, hand the result to a model. **Improving performance and deploying it is a different problem.** Tuning the pipeline, algorithms and hyperparameters one by one shows why it gets complex. Building the retrieval-generation loop myself also led me to think about agentic flows — tool calls and state.
- Ultimately, **quality is decided by data — parsing, chunking, evaluation sets — more than by swapping models**. What AI shortened was the typing of implementations and tests; deciding what counts as correct — how to restore tables, how to index Korean queries, what belongs in the golden set — still needed my judgment. That is why most of the schedule went into table parsing, Korean retrieval, goldens and cross-language parity.
- I also learned how to work with AI. I remain responsible for direction and final approval, while using AI for iterative implementation and verification. That experience naturally led to another experiment: what if a stronger reasoning model broke down and reviewed the work, while a lighter model handled implementation? Could that loop run across several tasks while preserving context, tracking progress, and keeping costs under control? I’m now working through those questions by putting the workflow into practice. 😎

## References {#references}

- [LangChain basics course](https://www.inflearn.com/course/입문자를위한-랭체인-기초)
- [Retrieval Augmented Generation (RAG)](https://www.coursera.org/learn/retrieval-augmented-generation-rag)
- [KodeKloud RAG Crash Course](https://www.youtube.com/watch?v=swvzKSOEluc)
- [freeCodeCamp: Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8)
- [BM25 study video](https://www.youtube.com/watch?v=ziiF1eFM3_4)
