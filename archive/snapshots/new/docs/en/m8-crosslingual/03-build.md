# M8 Build — The query gets a language, and the gap gets a number

## Here is where the question stops being assumed English

Every retrieval decision so far was made for a corpus of English filings asked English questions. That assumption is not written down anywhere; it is baked into one text-search configuration and inherited by every arm that touches it. M8 does not start by fixing that. It starts by building a Korean question set that differs from the English one in exactly one field, so that the gap between the two can be measured before anyone argues about its cause — and only then enters routing and translation as arms that have to earn their numbers.

## Checkpoint map

| Order | Checkpoint | Goal | Canonical files |
|---:|---|---|---|
| 1 | M8.1 | Korean twins over the same immutable spans | `data/golden/retrieval_ko.json`, `app/evals/bilingual.py` |
| 2 | M8.2 | Arms, diagnostics, and the before table | `app/evals/crosslingual.py` |
| 3 | M8.3 | Detection, routing, and translation as arms | `app/retrieval/language.py`, `translate.py`, `service.py`, `app/config.py` |
| 4 | M8.4 | The parity definition and its gate | `app/evals/parity.py`, `app/evals/crosslingual.py` |

This module touches `app/evals`, `app/retrieval`, `data/golden`, and `tests/crosslingual`. Three of those touches are additive; the fourth adds one parameter to `retrieve()` and one field to `Settings`, both defaulted off.

## Tutorial — built in four sittings

M8 produces five new modules and about 1,300 lines of Python, plus one 622-line golden file. Each document targets **under 30 minutes** to read and implement.

| Document | Checkpoint | Files built | Approx. |
|---|---|---|---|
| [1. The bilingual golden suite](tutorial/01-bilingual-golden.md) | M8.1 | `retrieval_ko.json`, `bilingual.py` | 30 min |
| [2. Measuring the collapse](tutorial/02-measuring-the-collapse.md) | M8.2 | `crosslingual.py` | 30 min |
| [3. Routing and translation](tutorial/03-routing-and-translation.md) | M8.3 | `language.py`, `translate.py`, `service.py`, `config.py` | 30 min |
| [4. The parity gate](tutorial/04-parity-gate.md) | M8.4 | `parity.py`, `crosslingual.py` | 25 min |

Follow them in order. Do not move on while a stretch's focused test is failing.

## Starting conditions

M1 through M7 are complete: the corpus is seeded, retrieval and its evaluation exist, the workflow runs, and the service is deployed. `data/golden/retrieval.json` is frozen and stays frozen — M8 adds a second file beside it and never edits the first.

## M8.1 — The data has to be identical before the metrics can differ

The Korean suite is twenty-eight cases that share their ids, taxonomy, and answer spans with the English suite and differ only in the question text. The suites live in two files because the loader refuses duplicate answer-span identities inside one batch, and the twin validator enforces the rest. The invariant this locks in is the one every later number depends on: **a ko/en metric gap can only be a fact about retrieval, because nothing else differs.**

**Document:** [1. The bilingual golden suite](tutorial/01-bilingual-golden.md) · **Passing:** `uv run pytest tests/crosslingual/test_01_bilingual.py -q`

## M8.2 — Measure the failure before owning it

An arm carries its own provenance — embedding space, strategy, language, handling — into the config dict that baselines match on, and feeds it straight to the M3 harness. Two diagnostics answer the two halves of "does the system recognize Korean at all" without a fix in sight: twin-query alignment measures the embedding space with no corpus and no database, and lexical candidate coverage counts how many Korean questions the English tsquery answers with nothing. The invariant: **the before table exists before the fix does, and it is a measurement rather than an assumption.**

**Document:** [2. Measuring the collapse](tutorial/02-measuring-the-collapse.md) · **Passing:** `uv run pytest tests/crosslingual/test_02_crosslingual.py -q`

## M8.3 — Two ideas, two arms, no beliefs

Language detection is a pure character scan over three Unicode ranges — no model, no API, no dependency on how the client normalized the text. Routing uses it to stop asking a component that cannot answer, and the skip is observable because the empty lexical ranking is in the result. Translation buys the lexical arm back at the price of one LLM call, through the existing fail-closed provider boundary, injected explicitly so no configuration flag can add a paid call to a request that never asked for one. The invariant: **each idea enters the matrix as an arm with its own name and its own row, so it can be wrong in public.**

**Document:** [3. Routing and translation](tutorial/03-routing-and-translation.md) · **Passing:** `uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q`

## M8.4 — A parity claim needs a floor, a tolerance, and a verdict

Parity is `delta` and `ratio` per higher-is-better metric between two arms that differ only in query language, gated on the recall ratio at a floor of `0.85`, fail-closed when the English slice is zero, and judged only on the arms that claim to have fixed something. A per-language regression tolerance above single-case granularity keeps one flipped case out of the verdict. Then the loop closes once, in public: baseline, failure analysis, change, re-measure, delta table. The invariant: **the improvement is the delta table, not the sentence next to it.**

**Document:** [4. The parity gate](tutorial/04-parity-gate.md) · **Passing:** `uv run pytest tests/crosslingual/test_05_parity.py -q`

## What you should be able to explain now

- **Why must the Korean cases live in a separate file rather than a `language` field?**
- **Why is the zero-candidate rate measured rather than asserted at 100%?**
- **Why does routing skip the lexical component instead of ignoring its result?**
- **Why does translation raise where decomposition falls back?**
- **Why does the parity gate refuse to judge the `direct` arm?**

The tutorials answer each of these with a failing value and the code that rejects it.

## What this module hands to the next one

A measured cross-lingual boundary: two golden suites bound to one set of spans, an arm matrix whose configs separate baselines per language and per vector space, a query path that can be told about language without being told to guess, and a parity ratio with a gate. Any future corpus in a second language — a DART filing set, a 20-F, a Korean-language annex — reuses the twin pattern and the gate unchanged, and has to produce the same table before it can claim to work.

---

## Reference baseline — the complete canonical files

The chapters above are the chronological build. The generated section below is the machine-verified final reference against the pinned `reference_revision`, not a bundle to paste before M8.1.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M8.1 — Complete checkpoint

#### Create or replace `data/golden/retrieval_ko.json`

<!-- file: data/golden/retrieval_ko.json -->
```json
[
  {
    "id": "m3c-01",
    "question": "AMD의 매출총이익률은 2018 회계연도에서 2019 회계연도까지 어떻게 변화했습니까?",
    "category": "multi_hop",
    "facet": "comparison",
    "tags": [],
    "answers": [
      {
        "doc_id": "AMD-FY2019",
        "source_sha256": "45e9c96250b900ff5d329b1e76515e4ac1d93ceb5a1c28dccb7fe8a1a0b5be14",
        "start_char": 643376,
        "end_char": 644582
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Gross margin increased from 38% to 43%, a rise of 5 percentage points.",
    "note": "Year-over-year percentage comparison in an MD&A table. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-02",
    "question": "Amazon Web Services의 G4ad 인스턴스에는 어떤 AMD 제품이 사용되며, 이 인스턴스는 어떤 워크로드를 위해 설계되었습니까?",
    "category": "simple_lookup",
    "facet": "factual",
    "tags": [],
    "answers": [
      {
        "doc_id": "AMD-FY2020",
        "source_sha256": "0701e9d39b48a773884521b74118a1540a4eda2241e27290035cafd82d6b4c96",
        "start_char": 251043,
        "end_char": 251333
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "AMD EPYC processors and the AMD Radeon Pro V520 GPU power G4ad, which was designed for virtual workstations, game streaming, and graphics rendering.",
    "note": "Named-product retrieval from narrative business disclosure. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-03",
    "question": "AMD는 TSMC와 관련하여 어떤 구체적인 7nm 공급 위험을 밝혔습니까?",
    "category": "simple_lookup",
    "facet": "risk",
    "tags": [],
    "answers": [
      {
        "doc_id": "AMD-FY2021",
        "source_sha256": "5ab3b2564e1b5f18a1fc6b8b60a307abc3be32ee902a59955b3038c504dbfd36",
        "start_char": 358705,
        "end_char": 358908
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "AMD said that insufficient TSMC wafer supply at 7 nm or smaller nodes could materially harm its business.",
    "note": "Concrete supplier-concentration risk with a process node and consequence. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-04",
    "question": "AMD는 Xilinx 인수와 관련하여 총 이전대가와 영업권을 각각 얼마로 인식했습니까?",
    "category": "simple_lookup",
    "facet": "factual",
    "tags": ["demo-hero"],
    "answers": [
      {
        "doc_id": "AMD-FY2022",
        "source_sha256": "df0ad96c282b7eab4c3387bc2ef772350004e37be21805622ab8503b5db02acd",
        "start_char": 1521761,
        "end_char": 1522518
      },
      {
        "doc_id": "AMD-FY2022",
        "source_sha256": "df0ad96c282b7eab4c3387bc2ef772350004e37be21805622ab8503b5db02acd",
        "start_char": 1522875,
        "end_char": 1524006
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Total purchase consideration was $48.793 billion and goodwill was $22.784 billion.",
    "note": "Two acquisition-accounting values in separate answer-bearing table rows. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-05",
    "question": "2022 회계연도에 AMD의 Data Center 부문 순매출은 Client 부문 순매출과 비교해 어떠했습니까?",
    "category": "multi_hop",
    "facet": "comparison",
    "tags": [],
    "answers": [
      {
        "doc_id": "AMD-FY2022",
        "source_sha256": "df0ad96c282b7eab4c3387bc2ef772350004e37be21805622ab8503b5db02acd",
        "start_char": 659886,
        "end_char": 660328
      },
      {
        "doc_id": "AMD-FY2022",
        "source_sha256": "df0ad96c282b7eab4c3387bc2ef772350004e37be21805622ab8503b5db02acd",
        "start_char": 661285,
        "end_char": 661525
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Data Center revenue was $6.043 billion and Client revenue was $6.201 billion, so Client was $158 million higher.",
    "note": "Same-year segment comparison using two answer-bearing table rows. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-06",
    "question": "AMD가 2023 회계연도에 선언한 주당 분기 현금배당금은 얼마입니까?",
    "category": "absent",
    "facet": "policy",
    "tags": [],
    "answers": [],
    "expected_label": "NOT_IN_DOCS",
    "reference_answer": "NOT_IN_DOCS",
    "note": "No declared quarterly cash-dividend amount was found in the immutable corpus; the negative remains pending author approval. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-07",
    "question": "2023 회계연도 AMD의 연구개발비는 얼마였습니까?",
    "category": "exact_number",
    "facet": "numeric",
    "tags": ["demo-hero"],
    "answers": [
      {
        "doc_id": "AMD-FY2023",
        "source_sha256": "0e9d83bd98b81b70050a88635171e721488f783eada9686fe21d6919ee1b668e",
        "start_char": 756006,
        "end_char": 756419
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "$5.872 billion.",
    "note": "Exact-number retrieval from a multi-year financial statement table. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-08",
    "question": "인텔은 2019년에 배당과 자사주 매입을 통해 얼마의 현금을 주주에게 환원했으며, 향후 어떤 자사주 매입 계획을 발표했습니까?",
    "category": "simple_lookup",
    "facet": "policy",
    "tags": [],
    "answers": [
      {
        "doc_id": "INTC-FY2019",
        "source_sha256": "9a7c79b6f02ac47f313dcf23020ae16d8fe7d82f8feeb0c51fc63e1d31f48474",
        "start_char": 680567,
        "end_char": 680782
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Intel paid $5.6 billion in dividends, repurchased $13.6 billion in shares, and announced an expected $20.0 billion repurchase over 15 to 18 months.",
    "note": "Capital-allocation policy with three values in narrative text. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-09",
    "question": "인텔의 2020 회계연도 매출 중 미국 외 지역 판매와 홍콩을 포함한 중국 청구액이 차지한 비중은 각각 얼마입니까?",
    "category": "simple_lookup",
    "facet": "risk",
    "tags": [],
    "answers": [
      {
        "doc_id": "INTC-FY2020",
        "source_sha256": "455d47c6c6fbf103cadef13a2959d795b4149ab297a451df95bbe6f393a08123",
        "start_char": 1368372,
        "end_char": 1368574
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Sales outside the United States accounted for 79% of revenue, and China including Hong Kong contributed 26%.",
    "note": "Geographic-concentration risk grounded in two explicit percentages. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-10",
    "question": "2021 회계연도에 인텔이 운영한 상업용 양자컴퓨팅 구독 서비스의 명칭은 무엇입니까?",
    "category": "absent",
    "facet": "factual",
    "tags": [],
    "answers": [],
    "expected_label": "NOT_IN_DOCS",
    "reference_answer": "NOT_IN_DOCS",
    "note": "No commercial quantum-computing subscription service was found in the immutable corpus; the negative remains pending author approval. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-11",
    "question": "인텔의 IOTG와 Mobileye 매출은 2020년 대비 2021 회계연도에 각각 얼마나 증가했으며, Mobileye의 증가를 이끈 요인은 무엇입니까?",
    "category": "multi_hop",
    "facet": "comparison",
    "tags": [],
    "answers": [
      {
        "doc_id": "INTC-FY2021",
        "source_sha256": "57e5533ca477d3796dae0fb6090fb7b7e992caa2a84cb5bf44f33aa5e75c9451",
        "start_char": 841700,
        "end_char": 841926
      },
      {
        "doc_id": "INTC-FY2021",
        "source_sha256": "57e5533ca477d3796dae0fb6090fb7b7e992caa2a84cb5bf44f33aa5e75c9451",
        "start_char": 842076,
        "end_char": 842266
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "IOTG increased $991 million and Mobileye increased $419 million; Mobileye's increase reflected improved vehicle production, COVID-19 recovery, and greater ADAS adoption.",
    "note": "Two business-line changes plus a disclosed causal explanation. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-12",
    "question": "인텔의 순매출과 매출총이익률은 2021 회계연도에서 2022 회계연도까지 어떻게 변화했습니까?",
    "category": "multi_hop",
    "facet": "comparison",
    "tags": ["demo-hero"],
    "answers": [
      {
        "doc_id": "INTC-FY2022",
        "source_sha256": "997ea49fc960f6763f4b530793f32f2bb5f2aff8f2a5d82af1f002a4adf58b4b",
        "start_char": 852452,
        "end_char": 854271
      },
      {
        "doc_id": "INTC-FY2022",
        "source_sha256": "997ea49fc960f6763f4b530793f32f2bb5f2aff8f2a5d82af1f002a4adf58b4b",
        "start_char": 859259,
        "end_char": 861539
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Net revenue fell from $79.024 billion to $63.054 billion, while gross margin fell from 55.4% to 42.6%.",
    "note": "Two-metric year-over-year comparison in separate table rows. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-13",
    "question": "인텔이 언급한 사이드채널 취약점 변종의 이름은 무엇이며, 인텔은 왜 해당 위험이 계속되는 것으로 설명했습니까?",
    "category": "simple_lookup",
    "facet": "risk",
    "tags": [],
    "answers": [
      {
        "doc_id": "INTC-FY2023",
        "source_sha256": "3cbfebb819e981fdfaf9f4988a342aa048c924edb5c8cec2738b4883e534ee4e",
        "start_char": 1136671,
        "end_char": 1136951
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Intel cited Spectre and Meltdown and said that additional categories and variants had been and were expected to keep being identified.",
    "note": "Security-risk retrieval with named variants and an explanation of persistence. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-14",
    "question": "2023 회계연도 인텔의 연구개발비는 얼마였으며, 순매출에서 차지하는 비중은 몇 퍼센트였습니까?",
    "category": "exact_number",
    "facet": "numeric",
    "tags": ["demo-hero"],
    "answers": [
      {
        "doc_id": "INTC-FY2023",
        "source_sha256": "3cbfebb819e981fdfaf9f4988a342aa048c924edb5c8cec2738b4883e534ee4e",
        "start_char": 779047,
        "end_char": 779979
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "$16.046 billion, representing 29.6% of net revenue.",
    "note": "Exact amount and normalized percentage in one table row. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-15",
    "question": "마이크론은 2020 회계연도에 어떤 재고자산 평가 및 원가흐름 정책을 적용했습니까?",
    "category": "simple_lookup",
    "facet": "policy",
    "tags": [],
    "answers": [
      {
        "doc_id": "MU-FY2020",
        "source_sha256": "a5f702d596436e391b1dda42db4a0906ad4a958798d657a81242b3acb00ef555",
        "start_char": 1667389,
        "end_char": 1667465
      },
      {
        "doc_id": "MU-FY2020",
        "source_sha256": "a5f702d596436e391b1dda42db4a0906ad4a958798d657a81242b3acb00ef555",
        "start_char": 1668198,
        "end_char": 1668302
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Inventories were carried at the lower of average cost or net realizable value, and amounts were removed on an average-cost basis.",
    "note": "Two exact accounting-policy sentences in one filing section. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-16",
    "question": "마이크론의 GDDR6 및 GDDR6X 제품은 어디에 사용되었으며, 마이크론은 GDDR6X의 차별점으로 무엇을 제시했습니까?",
    "category": "simple_lookup",
    "facet": "factual",
    "tags": [],
    "answers": [
      {
        "doc_id": "MU-FY2021",
        "source_sha256": "f11f776395eb190170a3bf119659b57698af160e1ddaa7e720bb7969a0894878",
        "start_char": 430572,
        "end_char": 431033
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "They were used in game consoles, PC graphics cards, and GPU-based data-center solutions; GDDR6X used innovative signal-transmission technology for very high speed and bandwidth.",
    "note": "Product-and-use-case retrieval from narrative business disclosure. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-17",
    "question": "마이크론의 2022 회계연도 DRAM 및 NAND 매출은 각각 얼마였습니까?",
    "category": "exact_number",
    "facet": "numeric",
    "tags": ["demo-hero"],
    "answers": [
      {
        "doc_id": "MU-FY2022",
        "source_sha256": "505ad891414a9ff60e9317a8b1a1820781208f48994d24353f38e41dcb1d5936",
        "start_char": 2174465,
        "end_char": 2175478
      },
      {
        "doc_id": "MU-FY2022",
        "source_sha256": "505ad891414a9ff60e9317a8b1a1820781208f48994d24353f38e41dcb1d5936",
        "start_char": 2178112,
        "end_char": 2178920
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "DRAM revenue was $22.386 billion and NAND revenue was $7.811 billion.",
    "note": "Two exact product-revenue rows with distinct source spans. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-18",
    "question": "중국 CAC는 마이크론 제품에 대한 심사 이후 무엇을 금지했으며, 마이크론은 어떤 판매 채널이 영향을 받았다고 밝혔습니까?",
    "category": "simple_lookup",
    "facet": "risk",
    "tags": ["demo-hero"],
    "answers": [
      {
        "doc_id": "MU-FY2023",
        "source_sha256": "224d728b9d6cc480d5b20a27c611074c4532a4cdd5b6f623b8828545f9733ab0",
        "start_char": 468317,
        "end_char": 468762
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Critical information infrastructure operators in China could not purchase Micron products; affected revenue included direct and distributor sales to mainland China and Hong Kong customers, plus some outside-China customers.",
    "note": "Geopolitical-risk case with a named regulator, prohibition, and channel impact. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-19",
    "question": "마이크론의 매출과 매출총이익은 2022 회계연도에서 2023 회계연도까지 어떻게 변화했습니까?",
    "category": "multi_hop",
    "facet": "comparison",
    "tags": [],
    "answers": [
      {
        "doc_id": "MU-FY2023",
        "source_sha256": "224d728b9d6cc480d5b20a27c611074c4532a4cdd5b6f623b8828545f9733ab0",
        "start_char": 641759,
        "end_char": 643237
      },
      {
        "doc_id": "MU-FY2023",
        "source_sha256": "224d728b9d6cc480d5b20a27c611074c4532a4cdd5b6f623b8828545f9733ab0",
        "start_char": 647826,
        "end_char": 649590
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Revenue fell from $30.758 billion to $15.540 billion, while gross margin moved from $13.898 billion (45%) to a $1.416 billion loss (-9%).",
    "note": "Comparison across a sharp reversal, including negative table values. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-20",
    "question": "마이크론이 2024 회계연도에 보고한 랜섬웨어 지급액은 얼마입니까?",
    "category": "absent",
    "facet": "risk",
    "tags": [],
    "answers": [],
    "expected_label": "NOT_IN_DOCS",
    "reference_answer": "NOT_IN_DOCS",
    "note": "No ransomware payment amount was found in the immutable corpus; the negative remains pending author approval. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-21",
    "question": "마이크론 이사회는 사이버보안 위험에 대한 감독을 어떤 방식으로 수행했습니까?",
    "category": "simple_lookup",
    "facet": "policy",
    "tags": [],
    "answers": [
      {
        "doc_id": "MU-FY2024",
        "source_sha256": "1d3523d9d69f031f8b83008b18f47a9210a001d488112d348b50ce4e3a129ba7",
        "start_char": 590152,
        "end_char": 590488
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "The full Board monitored strategic cyber-risk exposure and administered oversight directly as a whole and through the Security Committee.",
    "note": "Concise Item 1C governance lookup with exact oversight roles. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-22",
    "question": "엔비디아의 매출과 매출총이익률은 2019 회계연도에서 2020 회계연도까지 어떻게 변화했습니까?",
    "category": "multi_hop",
    "facet": "comparison",
    "tags": [],
    "answers": [
      {
        "doc_id": "NVDA-FY2020",
        "source_sha256": "1f4c257e5e3b63cc3c8e0017572fe47cfe15daed2867255221f5dd5576b07c4d",
        "start_char": 558289,
        "end_char": 560408
      },
      {
        "doc_id": "NVDA-FY2020",
        "source_sha256": "1f4c257e5e3b63cc3c8e0017572fe47cfe15daed2867255221f5dd5576b07c4d",
        "start_char": 560663,
        "end_char": 562314
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Revenue fell 7%, from $11.716 billion to $10.918 billion, while gross margin increased 80 basis points from 61.2% to 62.0%.",
    "note": "A declining dollar metric paired with an improving percentage metric. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-23",
    "question": "Mellanox 인터커넥트가 포함된 엔비디아 플랫폼은 무엇이며, 엔비디아는 인수 이후 어떤 새로운 프로세서 종류를 발표했습니까?",
    "category": "simple_lookup",
    "facet": "factual",
    "tags": [],
    "answers": [
      {
        "doc_id": "NVDA-FY2021",
        "source_sha256": "5c76d41beb044bed6ae5286dff49f22349b65907e61da0dbbe513381a2d31213",
        "start_char": 261163,
        "end_char": 261677
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Mellanox interconnects were included in DGX, HGX, and EGX; NVIDIA announced the data processing unit (DPU), supported by DOCA.",
    "note": "Acquisition-to-product linkage using uncommon retrieval terms. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-24",
    "question": "NVIDIA Grace는 무엇이며, 엔비디아가 구축하려 한 기후 대응 슈퍼컴퓨터는 무엇입니까?",
    "category": "simple_lookup",
    "facet": "factual",
    "tags": [],
    "answers": [
      {
        "doc_id": "NVDA-FY2022",
        "source_sha256": "f6f5263c402599b2eb0de04ddfb0e4e6bcd9cab08f3c2a1792d6df108daa559d",
        "start_char": 517875,
        "end_char": 517933
      },
      {
        "doc_id": "NVDA-FY2022",
        "source_sha256": "f6f5263c402599b2eb0de04ddfb0e4e6bcd9cab08f3c2a1792d6df108daa559d",
        "start_char": 518063,
        "end_char": 518174
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Grace was NVIDIA's first Arm-based data-center CPU; Earth-2 was the planned AI supercomputer for addressing climate change.",
    "note": "Two exact product-announcement fragments from one narrative paragraph. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-25",
    "question": "2022 회계연도 엔비디아의 연구개발비는 얼마였으며, 2021 회계연도 대비 얼마나 증가했습니까?",
    "category": "exact_number",
    "facet": "numeric",
    "tags": ["demo-hero"],
    "answers": [
      {
        "doc_id": "NVDA-FY2022",
        "source_sha256": "f6f5263c402599b2eb0de04ddfb0e4e6bcd9cab08f3c2a1792d6df108daa559d",
        "start_char": 581971,
        "end_char": 583747
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "$5.268 billion, up $1.344 billion from $3.924 billion.",
    "note": "Exact amount and absolute delta in one table row. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-26",
    "question": "2023 회계연도에 중국을 대상으로 한 미국의 신규 수출 허가 요건은 엔비디아의 어떤 제품에 영향을 미쳤습니까?",
    "category": "simple_lookup",
    "facet": "risk",
    "tags": ["demo-hero"],
    "answers": [
      {
        "doc_id": "NVDA-FY2023",
        "source_sha256": "a4c77324eba4a3d88d46428ee097531930b75e46e983816352c76eff927621b7",
        "start_char": 446717,
        "end_char": 447097
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "The requirements affected A100 and H100 integrated circuits, DGX and other systems or boards containing them, A100X, and future circuits or systems meeting specified performance thresholds.",
    "note": "Export-control risk with exact model names and future-product thresholds. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-27",
    "question": "엔비디아 이사회가 2024 회계연도에 승인한 임직원 의무 비밀번호 변경 주기는 얼마입니까?",
    "category": "absent",
    "facet": "policy",
    "tags": [],
    "answers": [],
    "expected_label": "NOT_IN_DOCS",
    "reference_answer": "NOT_IN_DOCS",
    "note": "No Board-approved employee password-rotation interval was found in the immutable corpus; the negative remains pending author approval. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  },
  {
    "id": "m3c-28",
    "question": "2024 회계연도 엔비디아의 매출과 순이익은 각각 얼마였습니까?",
    "category": "exact_number",
    "facet": "numeric",
    "tags": [],
    "answers": [
      {
        "doc_id": "NVDA-FY2024",
        "source_sha256": "3ee6c75beb947d9e815464e5c0b6392db4f8ca20aa2f99666bc17c92b82d7759",
        "start_char": 745773,
        "end_char": 746412
      },
      {
        "doc_id": "NVDA-FY2024",
        "source_sha256": "3ee6c75beb947d9e815464e5c0b6392db4f8ca20aa2f99666bc17c92b82d7759",
        "start_char": 775222,
        "end_char": 775871
      }
    ],
    "expected_label": "SUPPORTED",
    "reference_answer": "Revenue was $60.922 billion and net income was $29.760 billion.",
    "note": "Two exact fiscal-year financial statement values in separate rows. Korean twin of the EN case.",
    "curation_status": "agent-curated",
    "approval_status": "pending-author-approval",
    "human_verified": false
  }
]
```

#### Create or replace `app/evals/bilingual.py`

<!-- file: app/evals/bilingual.py -->
```python
"""Paired Korean and English golden suites over one immutable set of answer spans."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import re

from app.evals.loader import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_MANIFEST_PATH,
    REPO_ROOT,
    load_golden_cases,
)
from app.evals.types import GoldenCase

KO_GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "retrieval_ko.json"

# The twin validator only has to answer "is there Korean text here", so it scans for
# Hangul directly instead of importing the M8.3 routing detector: the suite contract
# must hold before any query-path code exists, and a shared helper would make the
# first checkpoint depend on the third.
HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

# Every field a retrieval metric could be attributed to. Holding all of them identical
# is what makes an en/ko metric gap a fact about retrieval rather than about the data.
TWIN_INVARIANT_FIELDS = (
    "category",
    "facet",
    "tags",
    "answers",
    "expected_label",
    "reference_answer",
)


class TwinCaseError(ValueError):
    """A Korean suite is not a faithful twin of its English counterpart."""


@dataclass(frozen=True, slots=True)
class BilingualSuite:
    """One English suite and its validated Korean twin, in shared case-id order."""

    en: tuple[GoldenCase, ...]
    ko: tuple[GoldenCase, ...]

    def pairs(self) -> tuple[tuple[GoldenCase, GoldenCase], ...]:
        """Return ``(en, ko)`` case pairs ordered by their shared id."""
        by_id = {case.id: case for case in self.ko}
        return tuple((case, by_id[case.id]) for case in self.en)

    def cases(self, language: str) -> tuple[GoldenCase, ...]:
        """Return the suite for one language, so a run can name its slice."""
        if language == "en":
            return self.en
        if language == "ko":
            return self.ko
        raise ValueError(f"unsupported suite language: {language}")


def _normalized(question: str) -> str:
    return " ".join(question.casefold().split())


def validate_twin_cases(
    en_cases: Sequence[GoldenCase],
    ko_cases: Sequence[GoldenCase],
) -> tuple[tuple[GoldenCase, GoldenCase], ...]:
    """Validate that two suites differ in exactly one field, and return the pairs.

    Twin cases share their ids, their taxonomy, and — decisively — their answer spans,
    so a Korean run and an English run are scored against the same immutable source
    coordinates. That is the whole reason the parity number means anything: if the
    suites could drift, a ko/en gap would be ambiguous between "retrieval is worse in
    Korean" and "the Korean cases ask something easier".

    ``reference_answer`` stays English on both sides. Retrieval scoring never reads it,
    and requiring identity makes the invariant checkable instead of approximate.

    The two suites must live in separate files. ``load_golden_cases`` rejects duplicate
    answer-span identities inside one loaded batch, and twins share every span by
    design, so loading a directory that holds both raises before this validator runs.
    """
    if not en_cases or not ko_cases:
        raise TwinCaseError("both twin suites must be nonempty")

    en_index = {case.id: case for case in en_cases}
    ko_index = {case.id: case for case in ko_cases}
    if len(en_index) != len(en_cases) or len(ko_index) != len(ko_cases):
        raise TwinCaseError("twin suites must not repeat a case id")
    if set(en_index) != set(ko_index):
        missing = sorted(set(en_index) ^ set(ko_index))
        raise TwinCaseError(f"twin suites do not cover the same cases: {', '.join(missing)}")

    pairs: list[tuple[GoldenCase, GoldenCase]] = []
    for case_id in sorted(en_index):
        english = en_index[case_id]
        korean = ko_index[case_id]
        for field in TWIN_INVARIANT_FIELDS:
            if getattr(english, field) != getattr(korean, field):
                raise TwinCaseError(f"{case_id} twins disagree about {field}")
        # Checked before the script rules: a copied-across question is the likely
        # authoring slip, and reporting it as "no Hangul" would name the symptom.
        if _normalized(english.question) == _normalized(korean.question):
            raise TwinCaseError(f"{case_id} twins share one untranslated question")
        if HANGUL.search(english.question) is not None:
            raise TwinCaseError(f"{case_id} English question contains Hangul")
        if HANGUL.search(korean.question) is None:
            raise TwinCaseError(f"{case_id} Korean question contains no Hangul")
        pairs.append((english, korean))
    return tuple(pairs)


def load_bilingual_suites(
    en_path: str | Path = DEFAULT_GOLDEN_PATH,
    ko_path: str | Path = KO_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> BilingualSuite:
    """Load both suites through the unmodified loader and validate them as twins.

    Two separate ``load_golden_cases`` calls, not one directory load: each file gets
    the loader's full SHA-256 and span-source verification, and the Korean file is
    bound to the same raw filings as the English one, for free.
    """
    en_cases = load_golden_cases(en_path, manifest_path=manifest_path)
    ko_cases = load_golden_cases(ko_path, manifest_path=manifest_path)
    validate_twin_cases(en_cases, ko_cases)
    order = sorted(en_cases, key=lambda case: case.id)
    ko_index = {case.id: case for case in ko_cases}
    return BilingualSuite(
        en=tuple(order),
        ko=tuple(ko_index[case.id] for case in order),
    )
```

Run the checkpoint:

```bash
uv run pytest tests/crosslingual/test_01_bilingual.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M8.2 — Complete checkpoint

#### Create or replace `app/evals/crosslingual.py`

<!-- file: app/evals/crosslingual.py -->
```python
"""Cross-lingual retrieval arms, query-path diagnostics, and the parity command."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
import json
import math
from pathlib import Path
import re
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import LexicalRanker, Settings, get_settings
from app.evals.bilingual import KO_GOLDEN_PATH, BilingualSuite, load_bilingual_suites
from app.evals.breakdown import GroupScore, breakdown_by_category
from app.evals.loader import DEFAULT_GOLDEN_PATH
from app.evals.parity import (
    DEFAULT_MIN_RECALL_RATIO,
    ParityAssessment,
    assess_parity,
    parity_markdown,
)
from app.evals.retrieval_eval import (
    RetrievalEvaluation,
    RetrievalStrategy,
    Retriever,
    build_chunking_batch,
    evaluate_retriever,
    make_retriever,
    persist_evaluation,
    temporary_corpus_session,
    write_evaluation_artifact,
)
from app.evals.types import GoldenCase
from app.llm import LLMProvider, ProviderBudget
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.language import QueryLanguage
from app.retrieval.sbert import MULTILINGUAL_SBERT_MODEL
from app.retrieval.service import retrieve
from app.retrieval.translate import QueryTranslation, translate_query
from app.retrieval.types import ChunkHit, RetrievalFilters

QueryHandling = Literal["direct", "routed", "translated"]
ProviderChoice = Literal["deterministic", "openai", "sbert", "sbert-multi"]

CROSSLINGUAL_SUITE: Final[str] = "m8-crosslingual-v1"
# The M3 ablation's winning chunk target. Chunking is held fixed so the only axes in
# this matrix are the ones the module is about: embedding space, retrieval strategy,
# query language, and query handling.
CROSSLINGUAL_TARGET_TEXT_CHARS: Final[int] = 1200
DETERMINISTIC_EMBEDDING_MODEL: Final[str] = "token-hash-384"
PROVIDER_CHOICES: Final[tuple[ProviderChoice, ...]] = (
    "deterministic",
    "openai",
    "sbert",
    "sbert-multi",
)
LANGUAGE_CHOICES: Final[tuple[QueryLanguage, ...]] = ("en", "ko")
HANDLING_CHOICES: Final[tuple[QueryHandling, ...]] = ("direct", "routed", "translated")
ARM_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RANKER_SLUG: Final[dict[str, str]] = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
STRATEGY_ORDER: Final[dict[str, int]] = {"lexical": 0, "vector": 1, "hybrid": 2}
HANDLING_ORDER: Final[dict[str, int]] = {"direct": 0, "routed": 1, "translated": 2}
LANGUAGE_ORDER: Final[dict[str, int]] = {"en": 0, "ko": 1}


def embedding_identity(provider: ProviderChoice, settings: Settings) -> tuple[str, str]:
    """Map one CLI provider choice onto the Settings provider and the model name.

    ``sbert-multi`` is not a new provider literal. It is the existing ``sbert``
    provider pointed at the multilingual checkpoint, which is natively 384
    dimensions, so the arm changes the vector space without changing the schema.
    """
    if provider == "deterministic":
        return "deterministic", DETERMINISTIC_EMBEDDING_MODEL
    if provider == "openai":
        return "openai", settings.embedding_model
    if provider == "sbert":
        return "sbert", settings.sbert_model
    if provider == "sbert-multi":
        return "sbert", MULTILINGUAL_SBERT_MODEL
    raise ValueError(f"unsupported embedding provider choice: {provider}")


@dataclass(frozen=True, slots=True)
class CrosslingualArm:
    """One measured cross-lingual retrieval arm and its canonical provenance."""

    embedding_provider: ProviderChoice
    embedding_model: str
    strategy: RetrievalStrategy
    language: QueryLanguage
    handling: QueryHandling = "direct"
    lexical_ranker: LexicalRanker | None = None
    translator_model: str | None = None
    dimensions: int = 384
    target_text_chars: int = CROSSLINGUAL_TARGET_TEXT_CHARS
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        """Reject arm shapes whose measured numbers could not be attributed."""
        if self.embedding_provider not in PROVIDER_CHOICES:
            raise ValueError(f"unsupported embedding provider: {self.embedding_provider}")
        if not self.embedding_model.strip():
            raise ValueError("embedding_model must be nonblank")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError(f"unsupported retrieval strategy: {self.strategy}")
        if self.language not in LANGUAGE_ORDER:
            raise ValueError(f"unsupported query language: {self.language}")
        if self.handling not in HANDLING_ORDER:
            raise ValueError(f"unsupported query handling: {self.handling}")
        if self.strategy == "vector":
            if self.lexical_ranker is not None:
                raise ValueError("vector retrieval must not name a lexical ranker")
        elif self.lexical_ranker not in RANKER_SLUG:
            raise ValueError(f"{self.strategy} retrieval requires an explicit lexical ranker")
        # Routing decides whether to ask the lexical component at all, so it only
        # means something where both components run. A "routed" vector arm would be
        # the direct vector arm under a label claiming a route it never took.
        if self.handling != "direct" and self.strategy != "hybrid":
            raise ValueError(f"{self.handling} handling requires the hybrid strategy")
        if (self.handling == "translated") != (self.translator_model is not None):
            raise ValueError("a translator model is required exactly for translated handling")
        if self.dimensions <= 0 or self.target_text_chars <= 0:
            raise ValueError("dimensions and target_text_chars must be positive")
        if self.k <= 0 or self.candidate_k < self.k or self.rrf_k <= 0:
            raise ValueError("k, candidate_k, and rrf_k are inconsistent")
        if ARM_NAME.fullmatch(self.name) is None:
            raise ValueError("arm name must be lowercase kebab-case")

    @property
    def name(self) -> str:
        """Return the kebab arm name, which must survive being used as a filename."""
        parts = ["xling", self.embedding_provider, self.strategy]
        if self.lexical_ranker is not None:
            parts.append(RANKER_SLUG[self.lexical_ranker])
        if self.handling != "direct":
            parts.append(self.handling)
        parts.append(self.language)
        return "-".join(parts)

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Order arms by retrieval path, then handling, then language."""
        return (
            STRATEGY_ORDER[self.strategy],
            HANDLING_ORDER[self.handling],
            LANGUAGE_ORDER[self.language],
            self.name,
        )

    def paired_with(self, language: QueryLanguage) -> CrosslingualArm:
        """Return the same arm measured in the other query language."""
        return CrosslingualArm(**{**asdict(self), "language": language})

    def to_config(self) -> dict[str, Any]:
        """Return the canonical config dict consumed by artifacts and baselines.

        ``embedding.model`` and ``query.language`` carry the whole weight of every
        regression number in this module: ``latest_comparable_baseline`` matches on
        the serialized config, so an arm that omitted either would be compared
        against a run in a different vector space or a different language and the
        comparison would look valid.

        ``retrieval.reranker`` is recorded as null rather than left out. The M2.6
        cross-encoder is an English-trained model, so it stays off in every arm here;
        writing that down makes a future run that switches it on visibly incomparable
        instead of quietly contaminating the Korean slice.
        """
        translator = (
            None
            if self.translator_model is None
            else {"provider": "openai", "model": self.translator_model}
        )
        return {
            "name": self.name,
            "chunking": {
                "strategy": "structure-aware",
                "target_text_chars": self.target_text_chars,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": {
                "strategy": self.strategy,
                "lexical_ranker": self.lexical_ranker,
                "reranker": None,
                "k": self.k,
                "candidate_k": self.candidate_k,
                "rrf_k": self.rrf_k,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "model": self.embedding_model,
                "dimensions": self.dimensions,
            },
            "query": {
                "language": self.language,
                "handling": self.handling,
                "translator": translator,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": self.embedding_provider == "openai"
                or self.handling == "translated",
                "populated_corpus_embeddings_modified": False,
            },
        }


@dataclass(frozen=True, slots=True)
class TwinCosine:
    """One twin pair's query-vector cosine under a single embedding provider."""

    case_id: str
    cosine: float


@dataclass(frozen=True, slots=True)
class TwinAlignment:
    """How closely one embedding space places Korean queries beside their twins."""

    provider: str
    pair_count: int
    mean_cosine: float
    min_cosine: float
    max_cosine: float
    pairs: tuple[TwinCosine, ...]


@dataclass(frozen=True, slots=True)
class LexicalCoverage:
    """How often the English lexical index returns nothing for one language."""

    language: QueryLanguage
    case_count: int
    zero_candidate_cases: int
    zero_candidate_rate: float
    mean_candidate_count: float
    zero_candidate_case_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LanguageRun:
    """One evaluated arm together with its per-category slice."""

    arm: CrosslingualArm
    evaluation: RetrievalEvaluation
    categories: tuple[GroupScore, ...]
    artifact_path: Path | None = None


@dataclass(slots=True)
class TranslationLog:
    """Ordered record of every translation a measured arm actually performed.

    A translation arm is the one non-deterministic part of this matrix. Recording
    what each query became is what lets a reported number be re-read later; without
    it the arm reports a score for queries nobody can reconstruct.
    """

    entries: list[tuple[str, QueryTranslation]] = field(default_factory=list)

    def record(self, original: str, translation: QueryTranslation) -> None:
        """Append one translated query in call order."""
        self.entries.append((original, translation))

    def payload(self) -> list[dict[str, str]]:
        """Return a JSON-ready record for the run artifact."""
        return [
            {
                "original": original,
                "translated": translation.translated_query,
                "source_language": translation.source_language,
            }
            for original, translation in self.entries
        ]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("cosine requires vectors of equal length")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("cosine is undefined for a zero vector")
    return dot / (left_norm * right_norm)


async def twin_query_alignment(
    provider: EmbeddingProvider,
    suite: BilingualSuite,
    *,
    provider_name: str = "unknown",
) -> TwinAlignment:
    """Measure how near each Korean query sits to its English twin, before any corpus.

    This is the cheapest honest answer to "does this embedding space recognize both
    languages at all": no database, no chunks, no retrieval. A token-hashing provider
    shares almost no tokens across the pair and lands near zero — near, not at, since
    384 hashed dimensions collide. A multilingual model places the twins close, and
    that difference is visible before a single arm is indexed.
    """
    pairs = suite.pairs()
    if not pairs:
        raise ValueError("twin alignment requires at least one pair")
    en_vectors = await provider.embed_documents([english.question for english, _ in pairs])
    ko_vectors = await provider.embed_documents([korean.question for _, korean in pairs])
    measured = tuple(
        TwinCosine(case_id=english.id, cosine=_cosine(en_vector, ko_vector))
        for (english, _), en_vector, ko_vector in zip(pairs, en_vectors, ko_vectors, strict=True)
    )
    cosines = [item.cosine for item in measured]
    return TwinAlignment(
        provider=provider_name,
        pair_count=len(measured),
        mean_cosine=sum(cosines) / len(cosines),
        min_cosine=min(cosines),
        max_cosine=max(cosines),
        pairs=measured,
    )


async def lexical_candidate_coverage(
    retriever: Retriever,
    cases: Sequence[GoldenCase],
    *,
    language: QueryLanguage,
    candidate_k: int = 20,
) -> LexicalCoverage:
    """Count how many questions the lexical arm answers with nothing at all.

    The retriever is injected rather than built from a session here, so the
    diagnostic is exercised offline against a scripted lexical arm and used in the
    measured run against ``make_retriever(session, strategy="lexical", ...)``.

    The rate is measured, not assumed. Korean questions about this corpus still carry
    Latin tokens — tickers, ``7nm``, ``G4ad`` — and the English tsquery can match
    those, so the collapse is partial in a way only the number shows.
    """
    if not cases:
        raise ValueError("lexical coverage requires at least one case")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    empty: list[str] = []
    total = 0
    for case in sorted(cases, key=lambda item: item.id):
        hits = await retriever(case.question, candidate_k)
        total += len(hits)
        if not hits:
            empty.append(case.id)
    return LexicalCoverage(
        language=language,
        case_count=len(cases),
        zero_candidate_cases=len(empty),
        zero_candidate_rate=len(empty) / len(cases),
        mean_candidate_count=total / len(cases),
        zero_candidate_case_ids=tuple(empty),
    )


def category_breakdown(evaluation: RetrievalEvaluation) -> tuple[GroupScore, ...]:
    """Slice one evaluation by golden category through the unmodified breakdown."""
    cases = [case.golden for case in evaluation.cases]
    scores = [case.score for case in evaluation.cases if case.score is not None]
    return breakdown_by_category(cases, scores)


def arm_comparison_markdown(runs: Sequence[LanguageRun]) -> str:
    """Render one row per measured arm in deterministic arm order."""
    if not runs:
        raise ValueError("comparison requires at least one run")
    lines = [
        "| Arm | Strategy | Handling | Language | Cases | Recall@k | Hit rate@k | MRR | P95 ms |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda item: item.arm.sort_key):
        score = run.evaluation.score
        lines.append(
            f"| {run.arm.name} | {run.arm.strategy} | {run.arm.handling} | "
            f"{run.arm.language} | {score.case_count} | {score.recall_at_k:.6f} | "
            f"{score.hit_rate_at_k:.6f} | {score.mrr:.6f} | "
            f"{run.evaluation.latency.p95_ms:.3f} |"
        )
    return "\n".join(lines)


def language_category_markdown(runs: Sequence[LanguageRun]) -> str:
    """Join the per-category slices of every run into one language-aware table.

    Language is not a breakdown dimension inside ``breakdown.py``; each language is a
    separate run of the unmodified harness, and the two are joined here at render
    time. That keeps ``GroupScore`` and the loader's span-identity rule untouched, and
    it is the same move M9.5 made when it sliced decomposition by category.
    """
    if not runs:
        raise ValueError("category table requires at least one run")
    lines = [
        "| Arm | Language | Category | Cases | Recall@k | Hit rate@k | MRR |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda item: item.arm.sort_key):
        for group in run.categories:
            lines.append(
                f"| {run.arm.name} | {run.arm.language} | {group.group} | "
                f"{group.case_count} | {group.recall_at_k:.6f} | "
                f"{group.hit_rate_at_k:.6f} | {group.mrr:.6f} |"
            )
    return "\n".join(lines)


def make_crosslingual_retriever(
    session: AsyncSession,
    arm: CrosslingualArm,
    *,
    provider: EmbeddingProvider | None,
    llm_provider: LLMProvider | None = None,
    provider_budget: ProviderBudget | None = None,
    translation_log: TranslationLog | None = None,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one arm's query handling on top of the unmodified M3 retriever factory.

    Every handling value is a wrapper, never a fork of the harness: ``direct`` is
    ``make_retriever`` itself, ``routed`` is the same production ``retrieve`` call
    with language routing switched on, and ``translated`` rewrites the query before
    handing it to the direct arm. The comparison is therefore between query paths,
    not between evaluation code paths.
    """
    if arm.handling == "direct":
        return make_retriever(
            session,
            strategy=arm.strategy,
            provider=provider,
            lexical_ranker=arm.lexical_ranker,
            candidate_k=arm.candidate_k,
            rrf_k=arm.rrf_k,
            filters=filters,
        )

    if arm.handling == "routed":

        async def routed(query: str, k: int) -> Sequence[ChunkHit]:
            result = await retrieve(
                session,
                query,
                provider=provider,
                k=k,
                candidate_k=arm.candidate_k,
                filters=filters,
                rrf_k=arm.rrf_k,
                route_by_language=True,
                lexical_ranker=arm.lexical_ranker,
            )
            return result.hits

        return routed

    if llm_provider is None or provider_budget is None:
        raise ValueError("translated handling requires an LLM provider and a budget")
    inner = make_retriever(
        session,
        strategy=arm.strategy,
        provider=provider,
        lexical_ranker=arm.lexical_ranker,
        candidate_k=arm.candidate_k,
        rrf_k=arm.rrf_k,
        filters=filters,
    )

    async def translated(query: str, k: int) -> Sequence[ChunkHit]:
        translation = await translate_query(
            query,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        if translation_log is not None:
            translation_log.record(query, translation)
        return await inner(translation.translated_query, k)

    return translated


def artifact_filename(recorded_at: datetime, arm: CrosslingualArm) -> str:
    """Return a UTC timestamped stable artifact filename for one arm."""
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{arm.name}.json"


async def run_arm(
    session: AsyncSession,
    arm: CrosslingualArm,
    suite: BilingualSuite,
    *,
    provider: EmbeddingProvider | None,
    artifact_dir: str | Path | None = None,
    recorded_at: datetime | None = None,
    llm_provider: LLMProvider | None = None,
    provider_budget: ProviderBudget | None = None,
    translation_log: TranslationLog | None = None,
) -> LanguageRun:
    """Evaluate one arm on its own language slice and optionally write its artifact.

    The arm supplies its config dict straight to ``evaluate_retriever`` instead of
    going through ``run_ablation``, whose config-equality check would force the M3
    ``ExperimentConfig`` shape and leave no place to record language or handling.
    Everything else — scoring, provenance, latency, artifact schema — is the M3
    harness untouched.
    """
    moment = recorded_at or datetime.now(UTC)
    retriever = make_crosslingual_retriever(
        session,
        arm,
        provider=provider,
        llm_provider=llm_provider,
        provider_budget=provider_budget,
        translation_log=translation_log,
    )
    evaluation = await evaluate_retriever(
        suite.cases(arm.language),
        retriever,
        suite=CROSSLINGUAL_SUITE,
        config=arm.to_config(),
        k=arm.k,
        recorded_at=moment,
    )
    artifact_path = None
    if artifact_dir is not None:
        artifact_path = write_evaluation_artifact(
            Path(artifact_dir) / artifact_filename(moment, arm),
            evaluation,
        )
    return LanguageRun(
        arm=arm,
        evaluation=evaluation,
        categories=category_breakdown(evaluation),
        artifact_path=artifact_path,
    )


def parity_pairs(
    runs: Sequence[LanguageRun],
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Assess parity for every arm that was measured in both languages."""
    by_identity: dict[tuple[str, str, str | None], dict[str, LanguageRun]] = {}
    for run in runs:
        identity = (run.arm.strategy, run.arm.handling, run.arm.lexical_ranker)
        by_identity.setdefault(identity, {})[run.arm.language] = run
    assessments: list[tuple[CrosslingualArm, ParityAssessment]] = []
    ordered = sorted(
        by_identity,
        key=lambda key: (STRATEGY_ORDER[key[0]], HANDLING_ORDER[key[1]], key[2] or ""),
    )
    for identity in ordered:
        slices = by_identity[identity]
        if set(slices) != {"en", "ko"}:
            continue
        assessments.append(
            (
                slices["ko"].arm,
                assess_parity(
                    slices["en"].evaluation,
                    slices["ko"].evaluation,
                    min_recall_ratio=min_recall_ratio,
                ),
            )
        )
    return tuple(assessments)


def gated_assessments(
    assessments: Sequence[tuple[CrosslingualArm, ParityAssessment]],
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Select the shipping arms whose parity the gate is allowed to judge.

    Only a hybrid arm with language-aware handling can claim parity. The direct arm
    is the "before" measurement — gating it would make the gate report the very
    failure the module was built to expose, and passing it would mean the routing
    change had not been measured at all.
    """
    return tuple(
        (arm, assessment)
        for arm, assessment in assessments
        if arm.strategy == "hybrid" and arm.handling != "direct"
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the cross-lingual measurement command."""
    parser = argparse.ArgumentParser(
        description="Measure retrieval on Korean and English twin queries and gate parity."
    )
    parser.add_argument("--suite", default=CROSSLINGUAL_SUITE)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--ko-golden", type=Path, default=KO_GOLDEN_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=PROVIDER_CHOICES, default="deterministic")
    parser.add_argument(
        "--languages",
        choices=LANGUAGE_CHOICES,
        nargs="+",
        default=list(LANGUAGE_CHOICES),
    )
    parser.add_argument(
        "--strategies",
        choices=("lexical", "vector", "hybrid"),
        nargs="+",
        default=["lexical", "vector", "hybrid"],
    )
    parser.add_argument(
        "--handling",
        choices=HANDLING_CHOICES,
        nargs="+",
        default=["direct"],
        help="Query-path variants to cross with every hybrid arm.",
    )
    parser.add_argument("--lexical-ranker", choices=("ts_rank_cd", "bm25"), default="ts_rank_cd")
    parser.add_argument("--translator-model", default="gpt-4.1-mini")
    parser.add_argument("-k", type=_positive_int, default=5)
    parser.add_argument("--candidate-k", type=_positive_int, default=20)
    parser.add_argument("--rrf-k", type=_positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--min-recall-ratio", type=float, default=DEFAULT_MIN_RECALL_RATIO)
    parser.add_argument("--persist-results", action="store_true")
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Exit nonzero when a shipping arm fails the ko/en recall parity floor.",
    )
    return parser.parse_args(argv)


def build_arms(args: argparse.Namespace, embedding_model: str) -> tuple[CrosslingualArm, ...]:
    """Expand the parsed command into the sorted, deduplicated arm matrix."""
    languages = list(dict.fromkeys(args.languages))
    strategies = list(dict.fromkeys(args.strategies))
    handlings = list(dict.fromkeys(args.handling))
    arms: list[CrosslingualArm] = []
    for strategy in strategies:
        for handling in handlings:
            if handling != "direct" and strategy != "hybrid":
                continue
            for language in languages:
                arms.append(
                    CrosslingualArm(
                        embedding_provider=args.provider,
                        embedding_model=embedding_model,
                        strategy=strategy,
                        language=language,
                        handling=handling,
                        lexical_ranker=None if strategy == "vector" else args.lexical_ranker,
                        translator_model=(
                            args.translator_model if handling == "translated" else None
                        ),
                        k=args.k,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                )
    if not arms:
        raise ValueError("the requested matrix contains no arms")
    return tuple(sorted(arms, key=lambda arm: arm.sort_key))


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    from app.db.bootstrap import bootstrap_schema
    from app.llm import OpenAILLMProvider, TokenPricing

    settings_provider, embedding_model = embedding_identity(args.provider, get_settings())
    settings = get_settings().model_copy(
        update={"embedding_provider": settings_provider, "sbert_model": embedding_model}
        if settings_provider == "sbert"
        else {"embedding_provider": settings_provider}
    )
    provider = get_embedding_provider(settings)
    suite = load_bilingual_suites(args.golden, args.ko_golden)
    arms = build_arms(args, embedding_model)
    recorded_at = datetime.now(UTC)

    llm_provider = None
    provider_budget = None
    if any(arm.handling == "translated" for arm in arms):
        # The key travels through Settings, exactly as it does for the embedding
        # provider. Reading it here rather than letting the SDK fall back to the
        # process environment keeps a configured-but-unexported ``.env`` key working
        # and keeps every paid boundary in this command sourced the same way.
        llm_provider = OpenAILLMProvider(
            model_name=args.translator_model,
            api_key=(
                settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
            ),
        )
        provider_budget = ProviderBudget(
            max_input_tokens=2_000,
            max_output_tokens=400,
            max_cost_usd=Decimal("0.05"),
            pricing=TokenPricing(
                input_per_million_usd=Decimal("0.4"),
                output_per_million_usd=Decimal("1.6"),
            ),
        )

    alignment = await twin_query_alignment(provider, suite, provider_name=args.provider)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    runs: list[LanguageRun] = []
    coverage: list[LexicalCoverage] = []
    translations = TranslationLog()
    try:
        batch = build_chunking_batch(CROSSLINGUAL_TARGET_TEXT_CHARS, settings=settings)
        async with temporary_corpus_session(
            engine,
            batch,
            provider,
            target_text_chars=CROSSLINGUAL_TARGET_TEXT_CHARS,
            embedding_provider=args.provider,
        ) as (session, indexing):
            lexical_probe = make_retriever(
                session,
                strategy="lexical",
                provider=None,
                lexical_ranker=args.lexical_ranker,
                candidate_k=args.candidate_k,
            )
            for language in dict.fromkeys(args.languages):
                coverage.append(
                    await lexical_candidate_coverage(
                        lexical_probe,
                        suite.cases(language),
                        language=language,
                        candidate_k=args.candidate_k,
                    )
                )
            for arm in arms:
                runs.append(
                    await run_arm(
                        session,
                        arm,
                        suite,
                        provider=provider,
                        artifact_dir=args.artifact_dir,
                        recorded_at=recorded_at,
                        llm_provider=llm_provider,
                        provider_budget=provider_budget,
                        translation_log=translations,
                    )
                )

        assessments = parity_pairs(runs, min_recall_ratio=args.min_recall_ratio)
        gated = gated_assessments(assessments)
        if args.gate and not gated:
            raise RuntimeError(
                "--gate requires a hybrid arm with routed or translated handling in both languages"
            )

        persisted = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as db_session:
                for run in runs:
                    if run.artifact_path is None:
                        continue
                    persisted.append(
                        await persist_evaluation(
                            db_session,
                            run.evaluation,
                            raw_artifact_path=run.artifact_path,
                        )
                    )
                await db_session.commit()

        return {
            "comparison_table": arm_comparison_markdown(runs),
            "category_table": language_category_markdown(runs),
            "parity_tables": [parity_markdown(assessment) for _, assessment in assessments],
            "twin_alignment": {
                "provider": alignment.provider,
                "pair_count": alignment.pair_count,
                "mean_cosine": alignment.mean_cosine,
                "min_cosine": alignment.min_cosine,
                "max_cosine": alignment.max_cosine,
            },
            "lexical_coverage": [asdict(item) for item in coverage],
            "indexing": asdict(indexing),
            "translations": translations.payload(),
            "artifacts": [str(run.artifact_path) for run in runs if run.artifact_path],
            "persisted": [asdict(result) for result in persisted],
            "gate": {
                "enabled": bool(args.gate),
                "arms": [arm.name for arm, _ in gated],
                "passed": all(assessment.passed for _, assessment in gated),
            },
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Run the cross-lingual measurement command and honour the parity gate."""
    args = arguments()
    result = asyncio.run(_run_cli(args))
    print(result["comparison_table"])
    print()
    print(result["category_table"])
    for table in result["parity_tables"]:
        print()
        print(table)
    print()
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"comparison_table", "category_table", "parity_tables"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.gate and not result["gate"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
```

#### Create or replace `app/retrieval/sbert.py`

<!-- file: app/retrieval/sbert.py -->
```python
"""Local sentence-transformer embeddings behind the shared provider boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

from app.retrieval.embeddings import EmbeddingProvider, _texts, validate_embeddings

# The multilingual sibling of the default model. It outputs 384 dimensions natively,
# so it drops into ``Settings.sbert_model`` without touching ``embed_dim``, the
# ``Vector(384)`` column, or any migration — the difference is entirely in the space
# the vectors live in, where Korean and English text sit near each other.
MULTILINGUAL_SBERT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class _EmbeddingMatrix(Protocol):
    """Array-like sentence-transformer output used by the provider boundary."""

    def tolist(self) -> list[list[float]]:
        """Return the encoded batch as nested Python floats."""
        ...


class _SentenceEncoder(Protocol):
    """Structural type for the lazily imported sentence-transformer."""

    def get_sentence_embedding_dimension(self) -> int | None:
        """Return the model output width when the model reports one."""
        ...

    def encode(
        self,
        sentences: Sequence[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
    ) -> _EmbeddingMatrix:
        """Encode one batch with the options required by this provider."""
        ...


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Local sentence-transformer embeddings behind the shared provider boundary.

    The model runs inside this process, so after the weights are cached there is no
    API key and no network call. ``sentence_transformers`` is imported lazily, which
    keeps ``app.retrieval`` importable when the project is installed without a torch
    backend extra.

    A local model is not interchangeable with a hosted one. Vectors produced here do
    not share a space with vectors produced by another model, so switching providers
    requires re-embedding every chunk. Mixing them yields no error, only meaningless
    neighbours.
    """

    def __init__(
        self,
        *,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimensions: int = 384,
        batch_size: int = 32,
    ) -> None:
        if not model:
            raise ValueError("embedding model must be nonempty")
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        if batch_size <= 0:
            raise ValueError("embedding batch size must be positive")
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._encoder: _SentenceEncoder | None = None

    def _load(self) -> _SentenceEncoder:
        """Import and construct the encoder once, then reuse it.

        Raises
        ------
        RuntimeError
            If no torch backend extra is installed.
        ValueError
            If the model's output width does not match the database column.
        """
        if self._encoder is not None:
            return self._encoder

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; run one of "
                "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
            ) from exc

        encoder = cast(_SentenceEncoder, SentenceTransformer(self.model))
        reported = encoder.get_sentence_embedding_dimension()
        if reported != self.dimensions:
            raise ValueError(
                f"model {self.model!r} produces {reported} dimensions, "
                f"but this database stores {self.dimensions}"
            )
        self._encoder = encoder
        return encoder

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode a batch off the event loop and validate before returning."""
        inputs = _texts(texts)
        if not inputs:
            return []

        encoder = self._load()

        def _encode() -> list[list[float]]:
            """Run the synchronous, CPU-bound forward pass in a worker thread."""
            return encoder.encode(
                inputs,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).tolist()

        vectors = await asyncio.to_thread(_encode)
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )
```

Run the checkpoint:

```bash
uv run pytest tests/crosslingual/test_02_crosslingual.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M8.3 — Complete checkpoint

#### Create or replace `app/retrieval/language.py`

<!-- file: app/retrieval/language.py -->
```python
"""Query-language detection for the cross-lingual retrieval path."""

from __future__ import annotations

from typing import Literal

QueryLanguage = Literal["en", "ko"]

# Korean reaches this boundary in three Unicode ranges: precomposed syllables,
# the conjoining jamo that decomposed (NFD) input carries, and the compatibility
# jamo an input method emits for a bare consonant or vowel. Scanning all three
# means a query is classified from its own characters, with no model, no API call,
# and no dependency on how the client normalized the text.
HANGUL_SYLLABLES = (0xAC00, 0xD7A3)
HANGUL_JAMO = (0x1100, 0x11FF)
HANGUL_COMPATIBILITY_JAMO = (0x3130, 0x318F)
HANGUL_RANGES = (HANGUL_SYLLABLES, HANGUL_JAMO, HANGUL_COMPATIBILITY_JAMO)


def contains_hangul(text: str) -> bool:
    """Return whether any character of ``text`` is a Hangul syllable or jamo."""
    return any(start <= ord(character) <= end for character in text for start, end in HANGUL_RANGES)


def detect_query_language(query: str) -> QueryLanguage:
    """Classify one nonblank query as Korean or English.

    Any Hangul makes the query Korean. Korean questions about this corpus are
    mixed by nature — ``"AMD의 7nm 공급 위험"`` carries a ticker, a unit, and a
    number in Latin script — so a majority-script rule would route exactly the
    queries this module exists to route. The rule is therefore presence, not
    proportion, and it is deliberately asymmetric: an English query never
    contains Hangul, so no English query can be misrouted.

    The blank rejection mirrors ``retrieve`` and ``lexical_statement``: a query
    that carries no language at all is a caller error, not a default to English.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    return "ko" if contains_hangul(query) else "en"
```

#### Create or replace `app/retrieval/translate.py`

<!-- file: app/retrieval/translate.py -->
```python
"""Fail-closed query translation through the existing structured LLM boundary."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator

from app.llm import LLMProvider, Prompt, ProviderBudget, StrictSchema
from app.retrieval.language import QueryLanguage, detect_query_language

TRANSLATE_SYSTEM_PROMPT = (
    "You translate retrieval queries about United States SEC 10-K filings into English. "
    "Return the English query and the language it came from. Keep tickers, product names, "
    "process nodes, fiscal years, and numbers exactly as they appear in the input, and do "
    "not answer the question or add words the input does not contain."
)


class QueryTranslationError(RuntimeError):
    """One translation request refused, failed validation, or stayed non-English."""


class QueryTranslation(StrictSchema):
    """One structured translation of a query into the corpus language."""

    translated_query: Annotated[StrictStr, Field(min_length=1)]
    source_language: QueryLanguage

    @model_validator(mode="after")
    def reject_blank_translation(self) -> Self:
        """Reject a whitespace-only translation instead of passing it downstream."""
        if not self.translated_query.strip():
            raise ValueError("translated_query must not be blank")
        return self


async def translate_query(
    query: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> QueryTranslation:
    """Translate one query into English, or raise rather than return the original.

    The provider is injected, never read from ``Settings``. A translation arm costs
    money and adds a network hop to the query path, so it can only be switched on by
    a caller that already holds a provider — a configuration flag could turn it on
    everywhere, including inside a request that never asked for it.

    Unlike ``decompose_query``, this call does not fall back to the input on failure.
    Decomposition is an optimization over a query the retriever can already run; a
    failed translation would leave the Korean query to be scored as if it had been
    translated, and the measured number would then describe an arm that never ran.

    Raises
    ------
    QueryTranslationError
        If the provider refuses, exhausts its budget, fails schema validation after
        one repair, or returns a query that still contains Hangul.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    prompt = Prompt(system=TRANSLATE_SYSTEM_PROMPT, user=query)
    result = await llm_provider.complete(prompt, QueryTranslation, provider_budget)
    if result.status != "ok" or result.parsed is None:
        raise QueryTranslationError(f"query translation failed: {result.status}")
    translation = result.parsed
    if detect_query_language(translation.translated_query) != "en":
        raise QueryTranslationError("translated query is not English")
    return translation
```

#### Create or replace `app/retrieval/service.py`

<!-- file: app/retrieval/service.py -->
```python
"""Production composition for deterministic hybrid retrieval."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf, LexicalRanker, get_settings
from app.db.models import DIM
from app.retrieval.bm25 import BM25_IDF_VARIANTS, bm25_search
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search
from app.retrieval.language import detect_query_language
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

RankedChunkId = Annotated[int, Field(gt=0)]
RESEARCH_AND_DEVELOPMENT = re.compile(r"\bR\s*&\s*D\b", flags=re.IGNORECASE)


def _normalize_query(query: str) -> str:
    """Expand the common R&D abbreviation for embedding and PostgreSQL FTS parity."""
    return RESEARCH_AND_DEVELOPMENT.sub("research development", query)


class ComponentRankings(BaseModel):
    """Ranked chunk identities from each retrieval component, without raw scores."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vector: tuple[RankedChunkId, ...]
    lexical: tuple[RankedChunkId, ...]


class RetrievalResult(BaseModel):
    """Fused evidence plus inspectable rank-only component provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[ChunkHit, ...]
    component_rankings: ComponentRankings


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    reranker: RerankProvider | None = None,
    route_by_language: bool | None = None,
    lexical_ranker: LexicalRanker | None = None,
    bm25_k1: float | None = None,
    bm25_b: float | None = None,
    bm25_idf: BM25Idf | None = None,
) -> RetrievalResult:
    """Run vector then lexical search through one session and fuse their ranks.

    The component adapters close over the same ``AsyncSession``. They are awaited
    sequentially by ``hybrid_search`` because concurrent use of one session is unsafe.
    Component scores stay inside their native lanes; only ranked chunk identities are
    exposed beside the fused hits. An omitted candidate limit expands to
    ``max(20, 4 * k)`` at this production boundary.

    With no reranker the fused list is truncated to ``k`` by fusion itself, which is
    the M2.7 behaviour. Supplying one turns the request into two stages: fusion keeps
    the full candidate list, and the reranker rescores it and returns the top ``k``.
    Retrieval therefore goes wide cheaply first, then narrow expensively.

    Reranked hits carry cross-encoder scores rather than fusion scores. Component
    rankings are unaffected because they record what each retriever proposed, not
    what survived reranking.

    ``route_by_language`` resolves from ``Settings.query_language_routing`` when it is
    omitted. With routing on and a Korean query, the lexical component is skipped and
    ranking is vector-only. The lexical index is built with the ``english`` text-search
    configuration, so that component contributes nothing for Korean anyway; asking it
    anyway costs a database round trip and, worse, gives fusion a component whose
    silence is indistinguishable from a considered "no candidates". A skipped component
    is visible instead: ``ComponentRankings.lexical`` is empty, so the taken route can
    be read off the result rather than inferred from the configuration.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    limit = max(20, 4 * k) if candidate_k is None else candidate_k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    settings = get_settings()
    active_lexical_ranker = settings.lexical_ranker if lexical_ranker is None else lexical_ranker
    active_bm25_k1 = settings.bm25_k1 if bm25_k1 is None else bm25_k1
    active_bm25_b = settings.bm25_b if bm25_b is None else bm25_b
    if active_lexical_ranker not in ("ts_rank_cd", "bm25"):
        raise ValueError("lexical_ranker must be 'ts_rank_cd' or 'bm25'")
    if active_bm25_k1 <= 0:
        raise ValueError("bm25_k1 must be positive")
    if not 0 <= active_bm25_b <= 1:
        raise ValueError("bm25_b must be between 0 and 1")
    active_bm25_idf = settings.bm25_idf if bm25_idf is None else bm25_idf
    if active_bm25_idf not in BM25_IDF_VARIANTS:
        raise ValueError("bm25_idf must be 'lucene' or 'robertson'")
    normalized_query = _normalize_query(query)
    active_routing = (
        settings.query_language_routing if route_by_language is None else route_by_language
    )
    skip_lexical = active_routing and detect_query_language(normalized_query) == "ko"

    active_provider = provider or get_embedding_provider()
    if active_provider.dimensions != DIM:
        raise ValueError(
            f"embedding provider dimension {active_provider.dimensions} does not match "
            f"database dimension {DIM}"
        )

    vector_hits: list[ChunkHit] = []
    lexical_hits: list[ChunkHit] = []

    async def vector_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        query_vector = await active_provider.embed_query(component_query)
        hits = await vector_search(
            session,
            query_vector,
            k=component_k,
            filters=component_filters,
        )
        vector_hits.extend(hits)
        return hits

    async def lexical_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        if skip_lexical:
            return []
        if active_lexical_ranker == "bm25":
            hits = await bm25_search(
                session,
                component_query,
                component_k,
                component_filters,
                k1=active_bm25_k1,
                b=active_bm25_b,
                idf=active_bm25_idf,
            )
        else:
            hits = await lexical_search(
                session,
                component_query,
                component_k,
                component_filters,
            )
        lexical_hits.extend(hits)
        return hits

    fused = await hybrid_search(
        normalized_query,
        limit if reranker is not None else k,
        filters,
        vector_search=vector_component,
        lexical_search=lexical_component,
        candidate_k=limit,
        rrf_k=rrf_k,
    )
    if reranker is not None:
        fused = await rerank_hits(
            normalized_query,
            fused,
            provider=reranker,
            top_k=k,
        )
    return RetrievalResult(
        hits=tuple(fused),
        component_rankings=ComponentRankings(
            vector=tuple(hit.chunk_id for hit in vector_hits),
            lexical=tuple(hit.chunk_id for hit in lexical_hits),
        ),
    )
```

#### Create or replace `app/config.py`

<!-- file: app/config.py -->
```python
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LexicalRanker = Literal["ts_rank_cd", "bm25"]
BM25Idf = Literal["lucene", "robertson"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: Literal["openai", "deterministic", "sbert"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    # Local sentence-transformer used when embedding_provider is "sbert". The
    # default produces exactly 384 dimensions, matching embed_dim and the
    # database column, so no migration is needed to switch.
    sbert_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: Literal[384] = 384
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
    openai_api_key: SecretStr | None = None
    lexical_ranker: LexicalRanker = "ts_rank_cd"
    # The lexical index is built with the "english" text-search configuration, so a
    # Korean query produces no lexical candidates and hybrid fusion silently degrades
    # to the vector arm. Enabling this makes retrieve() skip the lexical component for
    # a Korean query instead, which is observable in ComponentRankings. Off by default:
    # M8 measures the collapse before changing the shipped query path.
    query_language_routing: bool = False
    bm25_k1: float = Field(default=1.2, gt=0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    bm25_idf: BM25Idf = "lucene"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Run the checkpoint:

```bash
uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M8.4 — Complete checkpoint

#### Create or replace `app/evals/parity.py`

<!-- file: app/evals/parity.py -->
```python
"""Cross-language parity metrics and the gate that keeps them honest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any, Final

from app.evals.regression import (
    HIGHER_IS_BETTER_METRICS,
    BaselineComparison,
    MetricName,
    RegressionTolerances,
    compare_against_baseline,
)
from app.evals.retrieval_eval import RetrievalEvaluation

DEFAULT_MIN_RECALL_RATIO: Final[float] = 0.85

# One positive case out of 24 moves a macro metric by about 0.042. A tolerance below
# that would let a single flipped case fail the gate, so the standing per-language
# regression allowance sits deliberately above single-case granularity.
PARITY_REGRESSION_TOLERANCE: Final[float] = 0.05

GATED_METRIC: Final[MetricName] = "recall_at_k"


@dataclass(frozen=True, slots=True)
class ParityMetric:
    """One metric measured on both language slices of the same arm."""

    metric: MetricName
    en: float
    ko: float
    delta: float
    ratio: float | None


@dataclass(frozen=True, slots=True)
class ParityAssessment:
    """The complete cross-language verdict for one arm pair."""

    suite: str
    k: int
    case_count: int
    min_recall_ratio: float
    metrics: tuple[ParityMetric, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether the gated ratio cleared its floor."""
        return not self.failures

    def metric(self, name: MetricName) -> ParityMetric:
        """Return one measured metric pair by name."""
        for result in self.metrics:
            if result.metric == name:
                return result
        raise KeyError(name)

    @property
    def recall_ratio(self) -> float | None:
        """Return the gated ko/en recall ratio, or None when the English slice is 0."""
        return self.metric(GATED_METRIC).ratio


def _config_identity(config: Mapping[str, Any], expected_language: str) -> dict[str, Any]:
    query = config.get("query")
    if not isinstance(query, Mapping) or "language" not in query:
        raise ValueError("parity requires an evaluation config carrying query.language")
    if query["language"] != expected_language:
        raise ValueError(f"expected a {expected_language} evaluation, got {query['language']!r}")
    identity = {key: value for key, value in config.items() if key != "name"}
    identity["query"] = {key: value for key, value in query.items() if key != "language"}
    return identity


def _case_ids(evaluation: RetrievalEvaluation) -> tuple[frozenset[str], frozenset[str]]:
    all_ids = frozenset(case.golden.id for case in evaluation.cases)
    scored_ids = frozenset(case.golden.id for case in evaluation.cases if case.score is not None)
    return all_ids, scored_ids


def assess_parity(
    en_eval: RetrievalEvaluation,
    ko_eval: RetrievalEvaluation,
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> ParityAssessment:
    """Compare two evaluations that differ only in query language.

    For each higher-is-better metric the assessment records ``delta = en - ko`` and
    ``ratio = ko / en``. The ratio is the claim the module makes — "Korean retrieves
    at least this fraction of what English retrieves" — and the delta is what the
    per-language regression gate watches over time.

    The ratio is undefined when the English slice scores 0, and that case fails
    closed. An arm whose English slice retrieves nothing has no parity to claim: the
    quotient 0/0 would read as perfect agreement while describing two dead arms.

    The two evaluations must be the same suite, the same ``k``, over the same case
    ids, under configs that agree on everything except ``query.language`` and the arm
    ``name`` that encodes it. Without that check a Korean run could be silently
    compared against an English run of a different provider or chunking, and the
    ratio would measure the wrong difference.
    """
    if not isinstance(en_eval, RetrievalEvaluation) or not isinstance(ko_eval, RetrievalEvaluation):
        raise TypeError("parity requires two RetrievalEvaluation values")
    if not math.isfinite(min_recall_ratio) or not 0.0 < min_recall_ratio <= 1.0:
        raise ValueError("min_recall_ratio must be in (0, 1]")
    if en_eval.suite != ko_eval.suite:
        raise ValueError("parity requires both evaluations to share one suite")
    if en_eval.score.k != ko_eval.score.k:
        raise ValueError("parity requires both evaluations to use the same k")

    en_ids, en_scored = _case_ids(en_eval)
    ko_ids, ko_scored = _case_ids(ko_eval)
    if en_ids != ko_ids or en_scored != ko_scored:
        raise ValueError("parity requires both evaluations to cover the same golden cases")
    if _config_identity(en_eval.config, "en") != _config_identity(ko_eval.config, "ko"):
        raise ValueError("parity arms must differ only in query language")

    en_values = en_eval.metric_values()
    ko_values = ko_eval.metric_values()
    metrics: list[ParityMetric] = []
    failures: list[str] = []
    for name in HIGHER_IS_BETTER_METRICS:
        english = en_values[name]
        korean = ko_values[name]
        ratio = None if english == 0.0 else korean / english
        metrics.append(
            ParityMetric(
                metric=name,
                en=english,
                ko=korean,
                delta=english - korean,
                ratio=ratio,
            )
        )
        if name != GATED_METRIC:
            continue
        if ratio is None:
            failures.append(f"{name}: English slice scored 0, so parity is undefined")
        elif ratio < min_recall_ratio and not math.isclose(
            ratio,
            min_recall_ratio,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            failures.append(f"{name}: ratio {ratio:.6f} is below the floor {min_recall_ratio:.6f}")

    return ParityAssessment(
        suite=en_eval.suite,
        k=en_eval.score.k,
        case_count=en_eval.score.case_count,
        min_recall_ratio=min_recall_ratio,
        metrics=tuple(metrics),
        failures=tuple(failures),
    )


def language_regression(
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    *,
    tolerance: float = PARITY_REGRESSION_TOLERANCE,
) -> BaselineComparison:
    """Compare one language slice with its own stored baseline.

    Parity is a ratio between two arms measured together; this is the other half of
    the gate, and it runs per language against ``latest_comparable_baseline``. Raising
    the Korean slice while quietly dropping the English one would improve the ratio,
    so the English slice keeps its own standing regression check.
    """
    return compare_against_baseline(
        baseline,
        current,
        tolerances=RegressionTolerances(
            recall_at_k=tolerance,
            hit_rate_at_k=tolerance,
            mrr=tolerance,
        ),
    )


def parity_markdown(assessment: ParityAssessment) -> str:
    """Render one parity assessment as a compact verdict table."""
    verdict = "PASS" if assessment.passed else "FAIL"
    lines = [
        "| Metric | EN | KO | Delta (EN-KO) | Ratio (KO/EN) |",
        "|---|---:|---:|---:|---:|",
    ]
    for result in assessment.metrics:
        ratio = "undefined" if result.ratio is None else f"{result.ratio:.6f}"
        lines.append(
            f"| {result.metric} | {result.en:.6f} | {result.ko:.6f} | "
            f"{result.delta:.6f} | {ratio} |"
        )
    lines.append("")
    lines.append(
        f"{verdict} — {assessment.suite}, k={assessment.k}, "
        f"{assessment.case_count} scored cases, "
        f"{GATED_METRIC} floor {assessment.min_recall_ratio:.2f}."
    )
    for failure in assessment.failures:
        lines.append(f"- {failure}")
    return "\n".join(lines)
```

Run the checkpoint:

```bash
uv run pytest tests/crosslingual/test_05_parity.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
