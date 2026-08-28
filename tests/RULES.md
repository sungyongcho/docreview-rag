# Test File Naming and Numbering Rules

This document defines how test files are named and organized under `tests/`.

The goal is to keep the relationship between implementation files and tests immediately visible while preserving tutorial order when one implementation module requires multiple test files.

## 1. One implementation file → one test file

When an implementation file requires only one test file, do not create a dedicated test directory and do not add a sequence number.

The test file should follow the implementation filename directly.

```text
app/ingestion/xref.py
        ↓
tests/ingestion/test_xref.py
```

Use:

```text
test_<implementation>.py
```

Do not use:

```text
xref/test_01_xref.py
test_06_xref.py
```

A directory and numbering add no useful information when there is only one corresponding test file.

---

## 2. One implementation file → multiple test files

When a single implementation file requires multiple test files, create a directory named after the implementation module.

Number the test files inside that directory according to the order in which the corresponding functionality is introduced in the tutorial.

```text
app/ingestion/parser.py
        ↓
tests/ingestion/parser/
├── test_01_blocks.py
├── test_02_rules.py
├── test_03_segment.py
├── test_04_validate.py
└── test_05_profile.py
```

Use:

```text
tests/<area>/<module>/test_<NN>_<feature>.py
```

The numbering is local to that implementation module.

It is not a global numbering scheme for the entire test suite.

For example, the existence of:

```text
parser/test_05_profile.py
```

does not require the next unrelated test to be named:

```text
test_06_xref.py
```

If `xref.py` has only one corresponding test file, it remains:

```text
test_xref.py
```

---

## 3. Numbering follows tutorial order

Numbers represent the learning and implementation order defined by the tutorial.

They do not represent:

- global test execution order
- implementation module order
- pytest execution order
- historical numbering inherited from another branch

When tests are reorganized, preserve the tutorial order of features within the corresponding implementation module.

Example:

```text
Tutorial:
blocks → rules → segmentation → validation → profiles

Tests:
parser/
├── test_01_blocks.py
├── test_02_rules.py
├── test_03_segment.py
├── test_04_validate.py
└── test_05_profile.py
```

Do not preserve old global numbers merely because the source branch used them.

---

## 4. Cross-module tests are not assigned to an implementation module

A test that directly combines behavior from multiple implementation modules should not be placed inside one module's test directory.

For example, if a test exercises both:

```text
parser.py
xref.py
```

and validates the resulting pipeline behavior, place it at the appropriate common test level instead.

Do not arbitrarily assign a cross-module test to `parser/` or `xref/`.

Name a common-level test file after the behavior scope it protects:

```text
test_<behavior_scope>.py
```

Use two or three concise lowercase words separated with underscores. Python test files
use snake case, not kebab case.

Examples:

```text
test_segmentation_routing.py
test_corpus_parsing.py
test_profile_lifecycle.py
test_xref_page_join.py
```

Do not combine a generic test category such as `regression`, `integration`, or `full`
with an implementation filename when that name does not describe the tested behavior.

---

## 5. Golden and corpus tests use behavior-scope names

Tests that validate assembled behavior against shared corpus data or fixed golden baselines are regression tests rather than direct implementation-file tests.

Their filenames still describe the protected behavior rather than the test category or
implementation filename:

```text
test_corpus_parsing.py
test_profile_lifecycle.py
test_xref_page_join.py
```

These files do not receive sequence numbers because they do not correspond to one implementation module or one step within that module.

Shared regression resources remain separate:

```text
tests/ingestion/
├── golden.py
├── conftest.py
├── test_corpus_parsing.py
├── test_profile_lifecycle.py
└── test_xref_page_join.py
```

Do not create a separate corpus file for every small behavior. Group assembled tests
by a major responsibility or lifecycle boundary so the suite remains easy to
navigate and maintain.

Prefer a small number of cohesive files such as:

```text
tests/ingestion/
├── test_corpus_parsing.py
├── test_profile_lifecycle.py
└── test_xref_page_join.py
```

Split a corpus or assembled-behavior file only when its tests have a materially
different fixture lifecycle, implementation boundary, or execution cost.

Inside a combined file, separate behavior groups with one short English
`#` comment. Do not use decorative multi-line comment banners.

Do not keep a derived assertion when a stronger exact assertion in the same suite
already guarantees it. Prefer one failure that identifies the protected contract over
several tests that restate the same result.

---

## 6. Determine placement from test responsibility

Do not move an entire test file mechanically based on its filename in the source branch.

Inspect the tests it contains and determine what they actually verify.

Use the following rule:

```text
One implementation module, one test file
    → test_<module>.py

One implementation module, multiple ordered test files
    → <module>/test_<NN>_<feature>.py

Multiple implementation modules / assembled behavior
    → common test level as test_<behavior_scope>.py

Corpus + golden baseline regression
    → common test level named after the protected behavior
```

If an existing test file mixes responsibilities, split or relocate individual tests as necessary rather than preserving the old file boundary.

The implementation structure and the current tutorial are authoritative. Historical test organization from another branch is not.

---

## 7. Test docstrings, comments, and output text

Each test function must have a short docstring of one to three lines that briefly
describes the behavior being tested.

Do not use NumPy-style docstring sections such as:

```text
Parameters
----------
Returns
-------
```

All comments and human-readable output text in tests must be written in English.

Output text includes:

- assertion failure messages
- pytest skip and xfail reasons
- fixture error messages
- diagnostic, log, and CLI text authored by the test suite

---

## 8. Share common fixtures and helpers

Do not redefine the same fixture, helper function, test-data builder, or constant in
multiple test files.

Place shared pytest fixtures in the nearest common `conftest.py` that contains every
test using them.

Place shared pure helpers, builders, and constants in an appropriately scoped support
module such as:

```text
tests/<area>/support.py
tests/<area>/<module>/support.py
```

Keep a helper inside one test file when only that file uses it. Move it to shared test
infrastructure only after another test file needs the same behavior.

Do not import reusable code from another `test_*.py` file. Test files contain test
cases; `conftest.py` and support modules contain shared test infrastructure.

Choose the narrowest common location. A parser-only helper does not belong in the root
`tests/conftest.py`, and an ingestion-only fixture does not belong above
`tests/ingestion/conftest.py`.
