# Meridian Code Academy — Demo Dataset (coding-school variant)

An original, fully synthetic corpus for the document-review workflow, modeled on the *genre*
of a peer-learning coding school's policies. Because the documents are invented, the golden
answers are exact ground truth — and there is no copyright or redistribution risk (see
`ATTRIBUTION.md`).

```
data/
├── seed/
│   ├── synthetic/        # 10 fictional MCA documents (full 7-category legal set)
│   └── public/           # optional real public docs (empty by default)
├── golden/
│   ├── retrieval_questions.json    # 23 Q&A with known source sections
│   ├── claim_support_cases.json    # 24 claims, 4 labels (6/6/6/6, with hard negatives)
│   └── review_checklist_cases.json # 6 scenarios scored item-by-item
├── ATTRIBUTION.md
└── validate_dataset.py
```

## The documents

These 10 documents mirror the full legal/terms set a coding school typically publishes
(privacy, API terms, cookies, legal notices, site terms, internal rules, video surveillance),
with conduct/exam/progression/security split out for finer citations.

| doc_id | File | What it's good for |
|---|---|---|
| MCA-PRIV | privacy-policy.md | retention lookups (12 numbered retention items) |
| MCA-API | api-terms-of-use.md | precise values: token TTL, secret rotation, rate limit; read-only/prohibited-use checks |
| MCA-RULES | internal-rules.md | **tiered sanctions (Tier 1/2/3)** + document-precedence clause |
| MCA-EXAM | exam-rules.md | exam conduct + cheating definitions |
| MCA-PROG | enrollment-and-progression.md | progression facts + cross-references |
| MCA-CHARTER | it-security-charter.md | "is this security action allowed?" reasoning |
| MCA-SITE | site-terms-of-use.md | **password rules** + account/acceptable-use checks |
| MCA-COOKIE | cookie-declaration.md | cookie retention + purposes |
| MCA-LEGAL | legal-notices.md | publisher/host facts + data-reuse rule |
| MCA-CCTV | video-surveillance-terms.md | surveillance retention/coverage/access |

## Why this corpus is a strong demo

The tiered-sanction structure (MCA-RULES §7) turns claim-checking into something a recruiter
immediately understands: a scenario like *"a student keeps a soda at their workstation"* maps
to a specific rule and a specific penalty. The claim set deliberately includes the realistic
failure mode where a claim cites the **right rule but the wrong tier** (CS-016), which is
exactly the kind of subtle error a grounded checker must catch.

## Citation scheme

Each document begins with `<!-- doc_id: MCA-XXX | version | effective -->`. Sections are
numbered headings (`## 7`, `### 7.1`). A citation is `(doc_id, section)`, e.g.
`MCA-RULES §7.1`. Golden files reference sources in this exact form.

## The labels

- **SUPPORTED / CONTRADICTED / NOT_IN_DOCS / PARTIALLY_SUPPORTED** for claims.
- Checklist items add **NEEDS_INFO** for scenarios that don't state enough to decide
  (e.g., RC-003: the app's encryption posture is unknown).

## Mapping to the project milestones

- **Milestone 2 (retrieval):** score against `retrieval_questions.json`.
- **Milestone 3 (workflow):** the checklist cases drive the bounded review workflow and
  structured report; NEEDS_INFO and the cross-document cases (e.g., CHARTER → RULES §7.3)
  exercise tool sequencing and the unsupported-claim guardrail.
- **Milestone 4 (evals):** `claim_support_cases.json` is the regression set. Track per-label
  accuracy; NOT_IN_DOCS and the wrong-tier PARTIALLY case make a good failure-analysis writeup.

## Maintenance

```
python data/validate_dataset.py
```

Fails (non-zero exit) if any golden case cites a section that doesn't exist. Wire it into CI.
