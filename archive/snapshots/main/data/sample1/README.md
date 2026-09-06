# DocReview RAG Agent — Demo Dataset

This folder is the evaluation dataset for the document-review workflow. It is deliberately
built around a **synthetic, fully-known corpus** so the golden answers are exact ground
truth — which is what makes the retrieval and claim-checking evals trustworthy.

```
data/
├── seed/
│   ├── synthetic/        # 6 fictional Northwind Labs policy docs (the demo corpus)
│   └── public/           # optional: real public docs (RFC 9110, OWASP ASVS, NIST) — see ATTRIBUTION.md
├── golden/
│   ├── retrieval_questions.json    # 16 Q&A with known source sections -> retrieval recall + citation correctness
│   ├── claim_support_cases.json    # 16 claims, 4 labels -> claim-checking eval (with hard negatives)
│   └── review_checklist_cases.json # 4 scenarios scored item-by-item -> checklist/report eval
├── ATTRIBUTION.md
└── validate_dataset.py   # checks every golden (doc_id, section) reference exists in the docs
```

## Why this corpus is "recruiter-easy"

The documents are an ordinary company knowledge base (HR, expenses, security, onboarding,
data retention, vendors). A non-technical reviewer can read a question like *"How many PTO
days does a new hire get?"*, see the answer with its highlighted citation, and judge
correctness in seconds — no domain expertise required. The rigor lives underneath, in the
eval files.

## Citation scheme

Every document starts with a header comment: `<!-- doc_id: HR-001 | version | effective -->`.
Sections are numbered headings (`## 2`, `### 2.1`). A citation is therefore
`(doc_id, section)`, e.g. `HR-001 §2.3`. Golden files reference sources in exactly this form,
so the system's output citations can be scored directly against them.

## The four claim labels (the point of the claim-checking eval)

- **SUPPORTED** — the documents directly back the claim.
- **CONTRADICTED** — the documents state the opposite.
- **NOT_IN_DOCS** — plausible but absent. This is the case naive RAG fails by inventing
  support; a guardrailed system must answer "not supported by the documents."
- **PARTIALLY_SUPPORTED** — one part holds, another is wrong or unstated.

Checklist cases add a third item-level result, **NEEDS_INFO**, for when a scenario doesn't
state enough to decide (e.g. RC-003: a DPA is required only if personal data is shared, and
the scenario doesn't say).

## How it maps to the project milestones

- **Milestone 2 (retrieval):** score retrieval against `retrieval_questions.json`
  (did the expected section come back in top-k?) and citation correctness.
- **Milestone 3 (workflow):** the checklist cases drive the bounded review workflow and the
  structured report; NEEDS_INFO exercises the unsupported-claim guardrail.
- **Milestone 4 (evals):** `claim_support_cases.json` is the regression set. Track per-label
  accuracy; the NOT_IN_DOCS and PARTIALLY_SUPPORTED rows are where regressions usually show
  up, so they make a good failure-analysis writeup.

## Maintenance

After editing any document or golden file, run:

```
python data/validate_dataset.py
```

It fails (non-zero exit) if any golden case cites a section that doesn't exist — wire it into
CI so a doc edit can never silently desync the ground truth.
