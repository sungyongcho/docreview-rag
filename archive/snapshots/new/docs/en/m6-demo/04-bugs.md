# M6 Bugs

These are concrete portfolio and demo failure modes with narrow regression guards.

## B01 — Presenting synthetic Acme evidence as a corpus result

**Symptom:** a README, screenshot, or recording describes the default Gradio answer as SEC retrieval evidence.

**Root cause:** `CannedDemoService` deliberately looks realistic so the UI can be tested without services, but its Acme filing is not in the committed manifest.

**Fix:** label the default launch `canned fixture`; reserve a local-runtime label for an explicitly injected runtime service.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/demo -k "canned_mode" -q
```

## B02 — Confusing UI launch with runtime integration

**Symptom:** a loopback URL opens successfully, so the milestone is declared end-to-end.

**Root cause:** UI construction and socket launch do not prove which service was injected.

**Fix:** keep loopback launch proof separate from the real return-type integration proof. Require visible mode labels and evidence from the committed corpus for a runtime recording.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/demo -k "runtime_adapter" -q
```

## B03 — Installing Gradio outside the lock

**Symptom:** the demo works on one machine but the optional dependency is absent or resolves differently on a clean setup.

**Root cause:** a direct package install bypasses the project extra and lockfile.

**Fix:** declare the optional `demo` extra, retain it in `uv.lock`, and use locked sync.

**Regression check:**

```bash
uv sync --locked --extra demo --dry-run
```

## B04 — Leaking credentials through trace presentation

**Symptom:** UI state or rendered errors contain `api_key`, `secret`, or an authorization value.

**Root cause:** passing raw settings or arbitrary exception objects into Gradio.

**Fix:** render only the typed `DemoTrace` fields and sanitized typed service errors. Never accept a provider key in the browser.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/demo -k "secret or fail_closed" -q
```

## B05 — Turning predecessor counts into arithmetic

**Symptom:** documentation reports 697 passed because M6.1 added six tests to a prior 691-pass run.

**Root cause:** test totals were summed instead of measured from one complete suite.

**Fix:** retain `691 passed, 1 skipped` only as the dated M5.3 predecessor checkpoint. The post-M6 suite was rerun and measured `697 passed, 1 skipped`.

**Regression check:**

```bash
uv run pytest -o addopts="" -q
```

## B06 — Using a screenshot placeholder as evidence

**Symptom:** a broken image, mock frame, or TODO placeholder appears under an evidence heading without qualification.

**Root cause:** portfolio layout work outruns verified integration.

**Fix:** use a text-only placeholder that explicitly says it is not evidence. Any future image must correspond to a passing revision and label its demo mode.

**Regression check:**

```bash
rg -n "placeholder|canned fixture|runtime" README.md docs/en/m6-demo docs/ko/m6-demo
```

## B07 — Letting copied source or links drift

**Symptom:** tutorial code differs from `app/demo.py`, or an index points to a missing file or heading.

**Root cause:** portfolio edits are treated as prose-only and skip repository synchronization.

**Fix:** source-anchor the rendering example and run the documentation checker across the root README, docs tree, and module route.

**Regression check:**

```bash
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
```

## B08 — Testing a fake return shape instead of the M5 domain result

**Symptom:** the focused runtime-adapter test passes, but a real injected `RuntimeApiServices` result would fail during evidence conversion.

**Historical root cause:** the demo adapter read `retrieval.results`; M5 returned `RetrievalResult.hits`, while the focused fake supplied a `results` attribute.

**Fix:** the adapter now reads `RetrievalResult.hits`; the regression constructs that real return type and asserts the fake `results` attribute is absent.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/demo tests/api/test_08_integration.py -q
```
