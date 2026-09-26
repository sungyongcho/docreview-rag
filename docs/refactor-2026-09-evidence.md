# DocReview refactor, September 2026 — evidence appendix

This appendix belongs to `refactor-2026-09.md`. It holds the per-candidate verdicts of both
cleanup rounds, the candidates the mapping lanes rejected before verification, the tests
removed in each round with the reason and the surviving test that covers the same live
behaviour, the test files deleted on the branch and the tests added on the branch.

Branch `refactor/remove-dead-code` (PR #220), base `main` at `cc2d7c2`, head `afc2bfd`.

How to read the tables:

- `id` is the candidate id used by the workflow maps (`wf1.json` for round 1, `wf3.json` for
  round 2). The lane prefix names the area (`api`, `agent`, `retrieval`, `evals`, `ops`, `web`,
  `tests`, `dup`, `tests-support`).
- `verifier votes` counts how many of the three independent verifiers defended the candidate
  (asked to keep it). Round 1 lenses: dynamic and framework reachability, operational surface,
  consumers and history. Round 2 lenses: producers, equivalence, consumers. A candidate went
  forward when fewer than two verifiers defended it.
- `disposition` is the editor's outcome at the time the batch ran. A few dispositions changed in
  later commits; the "Outcome after the last commit" list after each table records those.


> Editor reports quote the commit ids they saw before the branch was rewritten to fix the committer identity. Their branch ids: `2fc1a68`→`50b7916`, `b09dc53`→`52de4c2`, `60aaee6`→`8511a33`, `a1ff295`→`9861ff7`, `ba1acc0`→`ae61683`, `a54a5c5`→`93eb315`, `f13ff25`→`c484120`, `aaf76ce`→`98e5756`, `3e84f69`→`fd984f2`, `81c5989`→`0cd4af8`, `b6dc5d0`→`ad33d0a`, `de0c794`→`c0928eb`, `1ba8ee0`→`bfc84b4`, `875e656`→`67eee06`, `8c2cd34`→`c3975cc`.

## Round 1: unreachable code

Dispositions in this table are the round-1 outcomes. Round 2 revisited several items that round 1 kept: the `/reset-local` page (web-14 → web-c01), the golden candidate files (evals-02/03 → evals-c02), the module CLIs (retrieval-01/09/10/11 → retrieval-c02/c03), `app/main.py` (see D-5) and `render_commands_markdown` (ops-06 → ops-c12); the round-2 table carries their final disposition.

| id | file | title | verifier votes (defended/3) | disposition |
|---|---|---|---|---|
| api-01 | `app/release/limiter.py` | Remove uncalled DailyCostLimiter.remaining() | 0 | deleted |
| api-02 | `app/api/review_profile.py` | Remove unused review_profile.zero_cost() and its only-use Decimal import | 0 | deleted |
| api-03 | `app/api/runtime.py` | Remove write-only bm25_b/bm25_idf plumbing into RuntimeApiServices | 0 | kept: The configured bm25_k1, bm25_b and bm25_idf are stored on RuntimeApiServices and never read, because the per-session retrieval profile always supplies BM25 values. The lane proposed removing only two of the three. This looks like missing wiring, not dead code, so it is left for a product decision. |
| api-04 | `app/api/runtime.py` | Remove never-passed RuntimeApiServices injection params snapshot_codec and snapshot_service | 0 | deleted |
| api-05 | `app/api/admin_runtime.py` | Remove never-passed RuntimeAdminApiServices injection params golden, snapshots and job_store | 0 | deleted |
| api-06 | `app/api/errors.py` | Remove never-passed ApiProblemError(corpus_job=...) parameter | 0 | deleted |
| api-07 | `app/release/__init__.py` | Delete docstring-only package file app/release/__init__.py | 0 | deleted |
| agent-01 | `app/workflow/gate.py` | Remove unused IntentClassification schema from the conversation gate | 0 | deleted |
| agent-02 | `app/workflow/runner.py` | Remove unused make_session_retriever binder, its imports and its test file | 0 | partly deleted (All 3 tests cover only make_session_retriever, so the whole file should go. But `rm tests/workflow/test_runner.py` was denied by the auto-mode permission classi) |
| agent-03 | `app/llm/openai_limits.py` | Remove unused OpenAILimitsManager.ceiling property | 0 | deleted |
| agent-04 | `app/openai_models.py` | Remove the uninvoked main() and __main__ block from app/openai_models.py | 0 | deleted |
| agent-05 | `app/openai_models.py` | Remove test-only default_openai_model and allowed_openai_models helpers | 0 | deleted |
| agent-06 | `app/agent/decompose.py` | CONDITIONAL: remove app/agent/decompose.py only if the evals lane deletes app/evals/decomposition.py | 0 | kept: The candidate was conditional on deleting app/evals/decomposition.py. That module is the agent evaluation CLI and stays, and it imports make_decomposed_retriever from this file, so the condition is not met. |
| retrieval-01 | `app/retrieval/__main__.py` | Retrieval experiment CLI module app/retrieval/__main__.py and its CLI-only tests | 0 | kept: docs/README_archive.md:633-641 documents `uv run python -m app.retrieval ...`, and README.md:81 links that archive as the full operator manual. The retrieval-11 operational verifier found this defence; it applies here too. The command still works. |
| retrieval-02 | `app/retrieval/hybrid.py` | hybrid.hybrid_search, the SearchCallable alias and their façade export | 0 | deleted |
| retrieval-03 | `app/retrieval/hybrid.py` | hybrid.rrf_fuse two-lane wrapper (depends on retrieval-02) | 0 | deleted |
| retrieval-04 | `app/ingestion/edgar.py` | edgar.SegmentType unused Literal alias and its typing import | 0 | deleted |
| retrieval-05 | `app/ingestion/edgar.py` | edgar.body_after unused helper | 0 | deleted |
| retrieval-06 | `app/ingestion/edgar.py` | edgar.py __main__ parser-inspection CLI and its Manifest import | 0 | deleted |
| retrieval-07 | `app/ingestion/edgar_api.py` | edgar_api.CORPUS_ROOT unused constant | 0 | deleted |
| retrieval-08 | `app/ingestion/edgar_api.py` | edgar_api.PARTIAL_SUFFIX unused constant | 0 | deleted |
| retrieval-09 | `app/ingestion/edgar_api.py` | edgar_api.py __main__ acquisition CLI plus parse_years (used only by that block) | 0 | kept: docs/README_archive.md:600-605 documents `uv run python -m app.ingestion.edgar_api --years ...` as an operator command, and README.md links it. A hermetic --help run confirmed it still parses. |
| retrieval-10 | `app/ingestion/dart_api.py` | dart_api.py __main__ acquisition CLI | 0 | kept: docs/README_archive.md:607-613 documents `uv run python -m app.ingestion.dart_api ...` as an operator command, and README.md links it. |
| retrieval-11 | `app/ingestion/progress.py` | progress.byte_bar, Overall and overall_bar terminal bars (depends on retrieval-09 and retrieval-10) | 1 | kept: Used only by the edgar_api and dart_api command blocks, which are kept (retrieval-09 and retrieval-10). The operational verifier defended it. |
| retrieval-12 | `app/ingestion/parser.py` | parser.read_source unused reader and its pathlib import | 0 | deleted |
| retrieval-13 | `app/ingestion/source_selection.py` | source_selection.catalogs unused catalog scanner | 0 | deleted |
| retrieval-14 | `app/ingestion/tables.py` | tables.table_captions one-line wrapper | 0 | deleted |
| retrieval-15 | `app/ingestion/tables.py` | tables.py __main__ eyeball helper | 0 | deleted |
| retrieval-16 | `app/ingestion/chunk.py` | chunk.py __main__ manual inspection helper | 0 | deleted |
| retrieval-17 | `app/ingestion/registry.py` | registry.resolve_registry wrapper (depends on retrieval-16) | 0 | deleted |
| evals-01 | `app/evals/curation.py` | Delete the golden-candidate curation module app/evals/curation.py and its tests | 0 | deleted |
| evals-02 | `data/golden/candidates/r1.json` | Delete the pending candidate batch data/golden/candidates/r1.json (only curation tests read it) | 0 | kept: A data file, not code. It records the provenance of the golden set and is outside a code-only dead-code change. |
| evals-03 | `data/golden/candidates/m10-r1.json` | Delete the superseded M10 candidate batch data/golden/candidates/m10-r1.json | 0 | kept: A data file, not code. It records the provenance of the golden set and is outside a code-only dead-code change. |
| evals-04 | `app/evals/breakdown.py` | Delete the unused breakdown_by_facet from app/evals/breakdown.py | 0 | deleted |
| evals-05 | `app/evals/breakdown.py` | Delete the unused breakdown_markdown renderer from app/evals/breakdown.py | 0 | deleted |
| evals-06 | `app/evals/loader.py` | Delete the unused DOC_ID_PATTERN constant and its import re from app/evals/loader.py | 0 | deleted |
| ops-01 | `main.py` | Delete the uv-init placeholder main.py at the repository root | 0 | kept (Deleting the whole file was blocked. The auto-mode permission classifier refused `rm /home/wwaya/Documents/docreview-rag/main.py` twice ([Irreversible Local Des) |
| ops-02 | `app/observability/cost.py` | Delete app/observability/cost.py (pinned price table and trace-cost helpers) and its test file | 0 | partly deleted (Whole-file deletion needs rm, which the permission classifier blocks in this session. git grep confirms that only tests/observability/test_cost.py references th; Blocked the same way (rm denied). Its live-behaviour assertions now run in tests/llm/test_schemas.py. Every other assertion in it covers only the dead estimate_) |
| ops-03 | `app/observability/stages.py` | Delete the unused observed_stage decorator from app/observability/stages.py | 0 | deleted |
| ops-04 | `app/corpus_admin.py` | Delete the dead CorpusAdminService Protocol and CannedCorpusAdminService fixture from app/corpus_admin.py | 0 | deleted |
| ops-05 | `app/corpus_admin.py` | Delete the unreferenced RuntimeCorpusAdminService.read_only property | 0 | deleted |
| ops-06 | `app/operator/commands.py` | Delete render_commands_markdown, a README table renderer used only by tests | 1 | kept: The consumers verifier defended it, and all three verifiers flagged the only-covering test list as wrong. Its two tests are the only snapshot of the live Operations COMMANDS registry (argv, descriptions, confirmation flags), so the function is a seam for tests of live behaviour. |
| ops-07 | `scripts/stack/environment.py` | Delete the unused CLI (main + write_null_environment) from scripts/stack/environment.py | 0 | deleted |
| ops-08 | `scripts/stack/quickstart.py` | Delete the retired __main__ entry of scripts/stack/quickstart.py | 0 | deleted |
| ops-09 | `scripts/stack/fresh.py` | Delete the retired __main__ entry of scripts/stack/fresh.py (former rag-start-fresh target) | 0 | deleted |
| ops-10 | `scripts/stack/commands.py` | Delete the unreachable start-fresh subcommand from scripts/stack/commands.py main | 0 | deleted |
| ops-11 | `app/cli.py` | Delete the unused ExitCode.INVALID_FILE member from app/cli.py | 0 | deleted |
| web-01 | `web/components/job-center.tsx` | Unused JobActivityPanel component and its CSS rules | 0 | deleted |
| web-02 | `web/components/measure-workspace.tsx` | Dead declarations in measure-workspace.tsx: MEASURE_TABS, lockedRuns, goldenAnswers | 0 | deleted |
| web-03 | `web/components/build-pipeline.tsx` | Unused splitList export in build-pipeline.tsx | 0 | deleted |
| web-04 | `web/components/runtime-settings.tsx` | Unused private formatSeconds in runtime-settings.tsx | 0 | deleted |
| web-05 | `web/components/review-progress.tsx` | Test-only progressCountsLabel in review-progress.tsx | 0 | deleted |
| web-06 | `web/lib/preparation-navigation.ts` | preparationTarget: its only non-test import is unused, so it is test-only | 0 | deleted |
| web-07 | `web/lib/i18n.tsx` | localizedDocumentationPath wrapper in i18n.tsx (test-only) | 0 | deleted |
| web-08 | `web/lib/canned.ts` | Unused CANNED_COMPARISON fixture in lib/canned.ts | 0 | deleted |
| web-09 | `web/lib/comparison-example.ts` | Unused COMPARISON_EXAMPLE constant in lib/comparison-example.ts | 0 | deleted |
| web-10 | `web/lib/types.ts` | Unused type aliases/interfaces in lib/types.ts | 0 | deleted |
| web-11 | `web/components/service-shell.tsx` | Unused import bindings in web modules | 0 | deleted |
| web-12 | `web/components/service-shell.tsx` | Unused destructured bindings (locale x13, dismissNotice) in components | 0 | deleted |
| web-13 | `web/lib/notification-registry.ts` | Orphan NOTIFICATION_EVENTS registry entries that no code emits | 0 | deleted |
| web-14 | `web/app/reset-local/page.tsx` | Orphan /reset-local route with its browser-clear helper and operator acknowledgement client | 0 | kept: Under this refactor's root policy every served page route is an entry point, just as every registered API route is. The page is also still exported to the Firebase site. Retiring the extreme-wipe acknowledgement flow (this page, POST /wipe/browser-cleared and the operator's awaiting_browser stage) should be one separate change. |
| tests-01 | `tests/ingestion/chunk/golden.py` | Delete orphaned chunk-count baseline module tests/ingestion/chunk/golden.py | 0 | deleted |
| tests-02 | `tests/ingestion/golden.py` | Delete unused LEGACY_FILES constant from tests/ingestion/golden.py | 0 | deleted |
| tests-03 | `tests/ingestion/golden.py` | Delete unused COVERAGE_BAND constant from tests/ingestion/golden.py | 0 | deleted |
| tests-04 | `tests/ingestion/golden.py` | Delete unused NVDA_FY2024_FILE path constant from tests/ingestion/golden.py | 0 | deleted |

Outcome after the last commit (round 1 items whose disposition changed later):

- agent-02: `tests/workflow/test_runner.py` was deleted in `ae61683`; the deletion the editor could
  not perform is complete.
- ops-01: `main.py` was deleted in `93eb315`.
- ops-02: `app/observability/cost.py` and `tests/observability/test_cost.py` were deleted in
  `93eb315`; the live `TokenPricing.estimate` assertions survive in
  `tests/llm/test_schemas.py::test_token_pricing_charges_cached_and_cache_write_input_at_policy_prices`.
- api-03 became the BM25 wiring fix `c484120` (decision D-4) instead of a deletion.
- retrieval-01, retrieval-09, retrieval-10 and retrieval-11 were removed in round 2
  (retrieval-c03 and retrieval-c02) under decision D-5, which retired the commands that only
  the archived README documents.
- evals-02 and evals-03 were removed in round 2 (evals-c02) once their last reader was gone.
- ops-06 was moved into its test in round 2 (ops-c12) instead of being deleted.
- web-14 was removed in round 2 (web-c01) together with the operator-side extreme wipe (ops-c01).
- agent-06 stays kept: `app/agent/decompose.py` is still imported by
  `app/evals/decomposition.py`.

## Round 2: compatibility, legacy and bloated code

| id | category | files | title | verifier votes (defended/3) | disposition |
|---|---|---|---|---|---|
| api-c01 | C1-legacy | `app/api/routes/ingest.py`, `app/api/routes/__init__.py`, `app/api/deps.py` … | Remove the POST /ingest seed route and the DOCREVIEW_ALLOW_INGEST knob | 0 | partly applied (Partial: the permission classifier denied the ReleaseGuardMiddleware edit as [Security Weaken], and I did not retry it. Everything tied to that guard is still i) |
| api-c02 | C1-legacy | `app/api/routes/admin.py`, `app/api/admin_runtime.py`, `schemas/api.openapi.json` … | Remove the superseded POST /admin/local-llm/connection and /admin/local-llm/reset routes | 0 | applied |
| api-c03 | C1-legacy | `app/api/routes/admin.py`, `app/api/admin_runtime.py`, `app/api/admin_schemas.py` … | Remove per-domain job routes superseded by the unified /admin/jobs board | 0 | applied |
| api-c04 | C1-legacy | `app/main.py`, `app/cli.py`, `app/api/runtime.py` | Remove the superseded M5 entrypoint: app/main.py, `app.cli serve`, runtime.build_runtime_services | 0 | applied |
| api-c05 | C1-legacy | `app/release/middleware.py`, `app/api/review_profile.py` | Drop the release guard's checks for pre-2026-09-06 top-level budget/max_context_chars | 0 | not applied (The permission classifier denied the app/release/middleware.py edit that removes the legacy top-level budget/max_context_chars public-control checks, classified) |
| api-c06 | C1-legacy | `app/release/config.py` | Remove the manual OpenAI pricing tombstone fields from ReleaseSettings | 0 | applied |
| api-c07 | C1-legacy | `app/release/config.py`, `app/config.py`, `scripts/diagnostics/ollama.py` | Drop the undocumented DOCREVIEW_LOCAL_LLM_* spellings of the local-engine settings | 0 | applied |
| api-c08 | C1-legacy | `app/api/evidence.py`, `app/api/runtime.py` | Make evidence snapshots always carry routing_queries (drop the pre-2026-09-07 None form) | 0 | applied |
| api-c09 | C1-legacy | `app/api/admin_runtime.py`, `docs/TUTORIAL/en/indexing.md`, `docs/TUTORIAL/ko/indexing.md` | Drop the job-board retry exemption for pre-2026-09-06 ingest rows without selection_id | 0 | applied |
| api-c10 | C2-shim | `app/api/runtime.py`, `tests/api/test_06_review_lifecycle.py`, `tests/release/test_02_release_app.py` | Remove RuntimeApiServices single-provider llm_provider/provider_budget adapter | 0 | applied |
| api-c11 | C3-bloat | `app/api/runtime.py`, `tests/api/test_06_review_lifecycle.py` | Remove dead RuntimeApiServices route_by_language/lexical_ranker service knobs | 0 | applied |
| api-c12 | C3-bloat | `app/api/runtime.py` | Remove _review's duplicate capability checks already enforced by _request_connection | 0 | kept: a duplicated authorization check stays as defence in depth |
| api-c13 | C3-bloat | `app/release/middleware.py` | Remove the no-op active_allowance set/reset in the release guard's non-shared branch | 0 | applied |
| api-c14 | C3-bloat | `app/release/limiter.py`, `tests/release/test_limiter.py` | Limiter: drop write-only _ClientWindow.last_seen and test-only client_count | 0 | applied |
| api-c15 | C3-bloat | `app/release/config.py` | Remove ReleaseSettings.port, a setting nothing reads | 0 | applied |
| api-c16 | C3-bloat | `app/api/admin_schemas.py`, `app/api/schemas.py` | Consolidate duplicated _tuple_from_json_array, RetrievalStrategy and RerankerName onto review_profile | 0 | applied |
| api-c17 | C3-bloat | `app/api/routes/stream.py` | Stream route: drop the hasattr/isinstance branches that only accommodate incomplete test fakes | 0 | applied |
| api-c18 | C3-bloat | `app/release/app.py` | Release readiness: drop the unreachable settings-built LocalModelInventory branch | 0 | applied |
| agent-c01 | C1-legacy | `app/llm/provider.py`, `tests/llm/test_provider.py`, `tests/release/test_ai_allowance.py` | Remove the legacy SDK-parsed path (structured_output=False) from OpenAILLMProvider | 0 | applied |
| agent-c02 | C1-legacy | `app/llm/local_connection.py`, `tests/llm/test_local_connection.py` | Stop reading version-1 local-llm.json connection files | 0 | not applied (The batch contract forbids narrowing a validator that reads persisted data, and names stored JSON files under data/ explicitly. The v1 branch in LocalConnection) |
| agent-c03 | C1-legacy | `app/llm/local_connection.py`, `app/api/admin_runtime.py`, `app/api/routes/admin.py` … | Retire the connect-by-URL save (POST /admin/local-llm/connection and LocalConnectionManager.connect) | 0 | applied |
| agent-c04 | C1-legacy | `app/workflow/gate.py`, `tests/llm/test_local.py` | Drop ChatReply and the casual_chat intent left over from the retired retrieval-free chat path | 0 | applied |
| agent-c05 | C3-bloat | `app/llm/provider.py`, `tests/llm/support.py`, `tests/llm/test_provider.py` … | Move the test-only DeterministicLLMProvider into a tests support module | 0 | applied |
| agent-c06 | C3-bloat | `app/llm/provider.py`, `app/llm/local.py` | Consolidate the identical prompt-projection overrides onto LLMProvider | 0 | applied |
| agent-c07 | C3-bloat | `app/llm/provider.py`, `app/agent/provider.py` | Share one OpenAI Responses usage parser between the review and agent adapters | 0 | applied |
| agent-c08 | C3-bloat | `app/openai_models.py`, `app/agent/provider.py`, `app/api/runtime.py` … | Replace OpenAIModelPricing with TokenPricing and drop five field-by-field re-wrappings | 0 | applied |
| agent-c09 | C3-bloat | `app/workflow/gate.py` | Remove the never-passed has_issuer_alias parameter and its dead routing branch | 0 | applied |
| agent-c10 | C3-bloat | `app/agent/loop.py`, `app/agent/builtin_tools.py`, `app/agent/decompose.py` | Drop agent-package keyword knobs that every caller leaves at the default | 0 | applied |
| agent-c11 | C3-bloat | `app/llm/provider.py`, `app/agent/provider.py`, `tests/agent/test_provider.py` | Remove the unused endpoint-override knobs from both OpenAI adapters | 0 | applied |
| agent-c12 | C3-bloat | `app/llm/estimate.py`, `app/llm/provider.py`, `tests/llm/test_estimate.py` | Inline the single-caller exceeds_allowance comparison wrapper | 0 | applied |
| agent-c13 | C3-bloat | `app/llm/local_inventory.py` | Reuse _placement inside LocalModelInventory.placement instead of re-deriving it | 0 | applied |
| agent-c14 | C3-bloat | `app/llm/local.py` | Remove the unreachable closed-client guard in LocalLLMProvider._request | 0 | applied |
| agent-c15 | C3-bloat | `app/llm/local_engine.py`, `app/api/runtime.py`, `tests/llm/test_local_engine.py` … | Inline the single-caller build_local_provider pass-through | 0 | partly applied (Passing inventory.protocol directly fails basedpyright: pyright infers LocalModelInventory.protocol as str, because literal types are widened for an unannotated) |
| agent-c16 | C1-legacy | `app/config.py` | Delete the review price fields that exist only to reject removed manual pricing | 0 | applied |
| agent-c17 | C3-bloat | `app/config.py`, `app/release/config.py` | Drop the unused alternate env spellings OPENAI_API_KEY_DEV and DOCREVIEW_LOCAL_LLM_* from Settings (and ReleaseSettings together) | 2 | kept: two verifiers showed OPENAI_API_KEY_DEV is the field-name spelling, not a legacy alias |
| agent-c18 | C3-bloat | `app/workflow/runner.py`, `tests/workflow/support.py`, `tests/workflow/test_02_run_lifecycle.py` … | Accept only RetrievalResult from the workflow retriever; wrap test hits in tests | 0 | applied |
| retrieval-c01 | C1-legacy | `app/ingestion/tables.py`, `tests/ingestion/test_tables.py`, `tests/ingestion/test_01_structural_budget.py` … | Remove the legacy grid-to-markdown table renderer kept only as a test oracle | 0 | applied |
| retrieval-c02 | C1-legacy | `app/ingestion/edgar_api.py`, `app/ingestion/dart_api.py`, `app/ingestion/progress.py` … | Remove the EDGAR/DART acquisition CLIs documented only in the archived README, plus their CLI-only knobs and terminal bars | 0 | applied |
| retrieval-c03 | C1-legacy | `app/retrieval/__main__.py`, `tests/retrieval/test_service.py`, `tests/retrieval/test_bm25.py` … | Delete the `python -m app.retrieval` experiment CLI superseded by `app.cli retrieve` and rag-dev corpus | 0 | applied |
| retrieval-c04 | C3-bloat | `app/ingestion/seed.py` | Fold single-caller prepare_seed_batch and its unused knobs into load_seed_batch | 0 | applied |
| retrieval-c05 | C3-bloat | `app/ingestion/parser.py`, `app/ingestion/edgar.py`, `app/ingestion/dart.py` … | Drop ParsedFiling.n_blocks/n_chars, kept for the removed inspection CLI | 0 | applied |
| retrieval-c06 | C3-bloat | `app/retrieval/rerank.py`, `tests/retrieval/test_rerank.py` | Make rerank_hits require its provider; the no-provider branch has no caller | 0 | applied |
| retrieval-c07 | C3-bloat | `app/retrieval/embeddings.py`, `tests/retrieval/test_embeddings.py` | Remove unused parameters matching_embedding(chunk=) and get_embedding_provider(client=) | 0 | applied |
| retrieval-c08 | C3-bloat | `app/retrieval/korean.py`, `tests/retrieval/test_korean.py` | Pin Korean n-gram width: drop the `grams` knob that every caller leaves at the default | 0 | applied |
| retrieval-c09 | C3-bloat | `app/ingestion/chunk.py` | Make section_units' context_header required; its only caller always passes one | 0 | applied |
| retrieval-c10 | C3-bloat | `app/retrieval/scope.py` | Delete the uncalled ManifestScopeIndex.issuer() lookup | 0 | applied |
| retrieval-c11 | C3-bloat | `app/retrieval/types.py` | Use one ChunkKind literal instead of a second copy in retrieval/types.py | 0 | applied |
| evals-c01 | C1-legacy | `app/evals/snapshots.py`, `tests/evals/test_snapshots.py`, `tests/evals/test_public_snapshot_details.py` | Drop the top-level config golden_sha256 fallback in snapshots._golden_sha256 | 0 | applied |
| evals-c02 | C3-bloat | `data/golden/candidates/r1.json`, `data/golden/candidates/m10-r1.json` | Delete orphaned golden candidate files left by the removed curation module | 0 | applied |
| evals-c03 | C3-bloat | `app/evals/loader.py` | Remove the dead error=/label= parameters of validate_unique_cases | 0 | applied |
| evals-c04 | C3-bloat | `app/evals/artifacts.py` | Drop encode_json_document's unused sort_keys option and inline it into its single caller | 0 | applied |
| evals-c05 | C3-bloat | `app/evals/loader.py` | Inline validate_golden_payload into load_golden_cases, its only caller | 0 | applied |
| evals-c06 | C3-bloat | `app/evals/scoring.py`, `tests/evals/test_scoring.py` | Delete test-only recall_at_k/hit_rate_at_k/mrr wrappers that duplicate score_suite | 0 | applied |
| evals-c07 | C3-bloat | `app/evals/bilingual.py` | Replace bilingual._normalized with the identical loader.normalized_question | 0 | applied |
| evals-c08 | C3-bloat | `app/evals/parity.py` | Render the parity verdict table through reporting.markdown_table instead of a hand-rolled copy | 0 | applied |
| evals-c09 | C3-bloat | `app/evals/breakdown.py` | Inline breakdown._grouped into breakdown_by_category, its only caller | 0 | applied |
| evals-c10 | C3-bloat | `app/evals/measurement.py`, `tests/evals/test_measurement.py` | Remove budget_seconds overrides that no caller sets in measurement.py | 0 | partly applied (Verifier conflict, safer option chosen: the proposal deletes the finite/positive check in measure_query_budget, but the equivalence lens showed it is reachable ) |
| evals-c11 | C3-bloat | `app/evals/corpus.py`, `app/evals/crosslingual.py`, `tests/evals/test_corpus.py` | Remove the always-None expected_documents knob from evals corpus preparation | 0 | applied |
| evals-c12 | C3-bloat | `app/evals/regression.py`, `app/evals/retrieval_eval.py`, `tests/evals/test_regression.py` | Accept only RegressionTolerances (not a raw mapping) in compare_against_baseline/persist_evaluation | 0 | applied |
| evals-c13 | C3-bloat | `app/evals/snapshots.py` | Reuse admin._default_session_factory in snapshots instead of a byte-identical copy | 0 | not applied (Already applied by earlier commit 3e84f69; app/evals/snapshots.py has no local _default_session_factory to delete.) |
| evals-c14 | C3-bloat | `app/evals/ablation.py` | Drop the DEFAULT_LEXICAL_RANKERS alias of LEXICAL_RANKERS | 0 | applied |
| evals-c15 | C3-bloat | `app/evals/run.py` | Remove the unreachable candidate_k re-check at the top of run._run_cli | 0 | applied |
| ops-c01 | C1-legacy | `app/operator/wipe.py`, `app/operator/service.py`, `scripts/stack/commands.py` … | Remove the retired operator-side extreme wipe (awaiting_browser, POST /wipe/browser-cleared, backup_confirmed) | 0 | applied |
| ops-c02 | C1-legacy | `scripts/stack/fresh.py`, `scripts/stack/cli.py`, `scripts/stack/prod.py` … | Collapse start_fresh to the only reachable mode (runtime-only, no extreme, no discard-tracked, no restart) | 0 | applied |
| ops-c03 | C1-legacy | `scripts/stack/commands.py`, `scripts/stack/quickstart.py`, `scripts/schema/recreate.py` … | Remove the retired rag-reset host clean start (commands reset, quickstart reset mode, recreate restart_planned) | 0 | applied |
| ops-c04 | C1-legacy | `scripts/stack/commands.py`, `tests/scripts/stack/test_stack_commands.py` | Drop LocalClient's wipe-preview rejection mapping left from the retired CLI web reset | 0 | applied |
| ops-c05 | C1-legacy | `scripts/diagnostics/ollama.py`, `scripts/stack/quickstart.py`, `tests/scripts/diagnostics/test_ollama.py` | Remove rag-dev doctor's legacy-metadata fallback for APIs without POST /admin/local-llm/diagnostics | 0 | applied |
| ops-c06 | C1-legacy | `deploy/gcp/operator_tunnel.sh`, `scripts/stack/operator_web.sh`, `scripts/stack/environment.py` … | Delete the retired SSH-tunnel management UI (operator_tunnel.sh stub, operator_web.sh, unused tunnel/origin/http port knobs) | 0 | applied |
| ops-c07 | C1-legacy | `deploy/gcp/deploy_env_config.sh`, `deploy/oracle/deploy_env_config.sh` | Stop accepting the legacy POSTGRES_PASSWORD name in the deploy env loaders | 0 | applied |
| ops-c08 | C1-legacy | `scripts/diagnostics/local_grade.py`, `tests/scripts/diagnostics/test_local_grade.py` | Drop the pre-change unbounded grade schema kept for comparison in the local grade benchmark | 0 | applied |
| ops-c09 | C1-legacy | `scripts/stack/refresh_dev_ui.py` | Read MODE only from the DEV container env in refresh_dev_ui | 0 | applied |
| ops-c10 | C1-legacy | `app/cli.py`, `tests/test_cli.py` | Remove the undocumented `app.cli serve` subcommand superseded by the Compose/Docker uvicorn entrypoint | 0 | applied |
| ops-c11 | C3-bloat | `app/cli.py` | Inline app/cli.py entrypoint() wrapper for a console script that does not exist | 0 | applied |
| ops-c12 | C3-bloat | `app/operator/commands.py`, `tests/operator/test_commands.py` | Move render_commands_markdown (archive-table renderer) out of `app/` into its only test | 0 | applied |
| ops-c13 | C3-bloat | `app/observability/persistence.py`, `tests/observability/support.py`, `tests/observability/test_01_run_persistence.py` … | Move persist_run_report (test-only wrapper) into tests/observability/support.py | 0 | applied |
| ops-c14 | C3-bloat | `app/operator/wipe.py` | WipeService: drop the never-used inspect(details=False) mode and the unwrapped audit-record fallback | 0 | applied |
| ops-c15 | C3-bloat | `app/corpus_admin.py` | Consolidate RuntimeCorpusAdminService._redact onto redact_sensitive_text(secret_values=...) | 0 | applied |
| ops-c16 | C1-legacy | `app/observability/usage.py` | Drop never-produced key aliases in usage identity/model-call parsing | 0 | applied |
| web-c01 | C1-legacy | `web/app/reset-local/page.tsx`, `web/app/reset-local/page.test.tsx`, `web/lib/reset-browser.ts` … | Remove the orphan /reset-local extreme-reset browser page and its helpers | 0 | applied |
| web-c02 | C1-legacy | `web/lib/storage.ts`, `web/lib/browser-storage-persistence.test.ts` | Drop the conversations:v1 key fallback and the pre-session-profile conversation migration | 0 | applied |
| web-c03 | C1-legacy | `web/components/local-connection-settings.tsx`, `web/components/local-connection-settings.test.tsx` | Remove the 'Saved connection' fallback for local-connection responses without a server catalog | 0 | applied |
| web-c04 | C1-legacy | `web/lib/answer-engine-state.ts` | Drop the answer-engine fallback for readiness snapshots without review_engines | 0 | applied |
| web-c05 | C1-legacy | `web/lib/types.ts`, `web/lib/storage.ts`, `web/components/service-shell.tsx` … | Remove the never-written Conversation.publishedScope legacy selection | 0 | applied |
| web-c06 | C1-legacy | `web/components/service-shell.tsx`, `web/components/service-shell.test.tsx` | Stop recognizing the pre-#219 Korean-translated interruption notice | 0 | applied |
| web-c07 | C1-legacy | `web/lib/storage.ts`, `web/lib/storage.test.ts` | Stop rewriting retired experiment-default fields on read | 0 | applied |
| web-c08 | C1-legacy | `web/components/review-path-choice.tsx`, `web/components/review-progress.tsx`, `web/components/review-stage-details.tsx` … | Remove rendering for the retired casual_chat intent and chat node | 1 | partly applied (Partial by choice: I kept 'casual_chat' in the ReviewPathDecision.intent and skippedNodes reason unions in web/lib/types.ts. Those types describe transcripts st) |
| web-c09 | C1-legacy | `web/lib/documentation-registry.json`, `web/lib/documentation-registry.mjs`, `web/lib/documentation-registry.d.mts` … | Remove legacy walkthrough/bookmark anchor redirects from the documentation site | 0 | applied |
| web-c10 | C1-legacy | `web/components/service-shell.tsx` | Remove openSettings aliases for settings categories renamed in f11f30b | 0 | applied |
| web-c11 | C3-bloat | `web/lib/pipeline.ts`, `web/components/document-inventory.tsx`, `web/components/build-workspace.tsx` … | Remove the unreachable portfolio-fixture pipeline source and the always-empty fallbackDocuments prop | 0 | applied |
| web-c12 | C3-bloat | `web/lib/canned.ts`, `web/lib/help-content.ts`, `web/components/service-shell.test.tsx` … | Move test-only fixtures and lookups out of the served modules | 0 | applied |
| web-c13 | C3-bloat | `web/components/build-pipeline.tsx`, `web/components/build-workspace.tsx`, `web/lib/pipeline.ts` … | Stop accepting a schema_status of "ok" that the API never emits | 0 | applied |
| web-c14 | C3-bloat | `web/lib/operator-api.ts` | Fold the operatorBaseUrl/operatorBase pass-through pair into one function | 0 | applied |
| dup-c01 | C3-bloat | `app/openai_models.py`, `app/agent/provider.py`, `app/api/runtime.py` … | Make the model policy price TokenPricing directly instead of rebuilding it field by field at five call sites | 0 | applied |
| dup-c02 | C3-bloat | `app/api/admin_schemas.py` | Derive the admin RetrievalProfile from CustomRetrievalProfile instead of redeclaring its ten fields and validate_plan | 0 | applied |
| dup-c03 | C3-bloat | `app/llm/provider.py`, `app/agent/provider.py` | Share one OpenAI Responses usage parser between the review provider and the agent tool provider | 0 | applied |
| dup-c04 | C3-bloat | `app/ingestion/dart_api.py` | Delete the byte-identical _declared_length copy in dart_api and reuse edgar_api's | 0 | applied |
| dup-c05 | C3-bloat | `app/evals/corpus.py` | temporary_corpus_session should call persist_seed_batch_with_stats instead of re-implementing it | 0 | applied |
| dup-c06 | C3-bloat | `app/api/schemas.py`, `app/api/admin_schemas.py` | Keep one _tuple_from_json_array BeforeValidator instead of three identical copies | 0 | applied |
| dup-c07 | C3-bloat | `app/corpus_admin.py`, `app/evals/admin.py`, `app/api/runtime.py` … | One lazy default session factory and one lazy engine accessor instead of five and two copies | 0 | applied |
| dup-c08 | C3-bloat | `scripts/schema/status.py`, `scripts/stack/quickstart.py`, `tests/scripts/schema/test_status.py` … | Local schema preparation should reuse the container gate's app.db.startup.prepare | 0 | applied |
| dup-c09 | C3-bloat | `app/llm/local_inventory.py` | LocalModelInventory.placement should reuse _placement instead of re-deriving it inline | 0 | applied |
| dup-c10 | C3-bloat | `app/corpus_admin.py` | CorpusAdminService._redact should pass its secrets to redact_sensitive_text instead of replacing them by hand first | 0 | applied |
| tests-support-c01 | C1-legacy | `tests/ingestion/chunk/conftest.py`, `tests/ingestion/chunk/test_05_golden.py` | Remove the study-stage CHUNK_MODULE override, skip-on-missing proxy and chunker fixture from the chunk conftest | 0 | applied |
| tests-support-c02 | C3-bloat | `tests/workflow/support.py`, `tests/llm/test_provider.py`, `tests/workflow/test_02_run_lifecycle.py` … | Consolidate duplicated TickClock and raw-provider-response builders into tests/workflow/support.py | 0 | applied |
| tests-support-c03 | C3-bloat | `tests/agent/support.py`, `tests/agent/test_decompose.py`, `tests/agent/test_builtin_tools.py` | Drop tests/agent/support.py hit, a re-implementation of tests/retrieval/support.hit with a fixed score | 0 | applied |
| tests-support-c04 | C3-bloat | `tests/ingestion/support.py`, `tests/ingestion/test_edgar_api.py`, `tests/ingestion/test_dart_api.py` | Delete the ingestion support run() wrapper, which only calls asyncio.run | 0 | applied |
| tests-support-c05 | C3-bloat | `tests/evals/test_ablation.py`, `tests/evals/test_02_isolated_corpus_evaluation.py`, `tests/evals/test_scoring.py` | Replace evals test-file redefinitions of SOURCE_SHA256 with the tests/evals/support constant | 0 | applied |
| tests-support-c06 | C3-bloat | `tests/workflow/support.py`, `tests/evals/support.py` | Drop builder parameters no caller passes in tests/workflow/support.py and tests/evals/support.py | 0 | applied |

Outcome after the last commit (round 2 items whose disposition changed later):

- api-c01: the remainder (the `allow_ingest` parameter of `ReleaseGuardMiddleware`, the `/ingest`
  403 guard, `ReleaseSettings.allow_ingest`, the `allow_ingest` entry in
  `app/settings_sources.py` and `DOCREVIEW_ALLOW_INGEST` in `deploy/huggingface/space.env.example`)
  was applied in `c3975cc`. `grep -n ingest app/release/middleware.py app/release/app.py` finds
  nothing on the branch head.
- api-c05: applied in `c3975cc`. `PUBLIC_MAX_CONTEXT_CHARS` and the top-level `budget` and
  `max_context_chars` checks are gone from `app/release/middleware.py` and
  `app/api/review_profile.py`.
- agent-c02: still not applied on purpose; `LocalConnectionManager._load` accepts
  `version` 1 and 2 (`app/llm/local_connection.py`).
- evals-c13: needed no edit; `app/evals/snapshots.py` imports `_default_session_factory` from
  `app.operator.jobs`.
- tests-support-c02: the shared `TickClock` and `raw` builders landed in `tests/llm/support.py`
  (the editor's chosen location), not `tests/workflow/support.py`.
- web-c08: `casual_chat` stays in the `ReviewPathDecision.intent` and `skippedNodes` unions and
  `"chat"` stays in `ReviewEventNode` in `web/lib/types.ts`, on purpose (stored transcripts).

## Rejected by the mapping lanes (never candidates)

- **api**: Remove DOCREVIEW_ENVIRONMENT from AliasChoices('MODE','DOCREVIEW_ENVIRONMENT') in ReleaseSettings/Settings — Load-bearing. Init kwargs match case-insensitively, so ReleaseSettings(MODE='prod') binds the unrelated `mode` field (canned|runtime) and fails. DOCREVIEW_ENVIRONMENT is the only constructor spelling for `environment` (used in ~10 tests); the snapshot experiment turned 54 tests red.
- **api**: Remove OPENAI_API_KEY_DEV from AliasChoices('OPENAI_API_KEY_LOCAL','OPENAI_API_KEY_DEV') — Load-bearing. It is the upper-cased field name, so it is what lets Settings(openai_api_key_dev=...) and Settings.model_validate({**settings.model_dump(), ...}) keep the key. app/cli.py _provider_settings uses that round-trip, and removing the alias silently dropped the key (tests/evals/test_crosslin
- **api**: RunResponse.from_run_report reconstruction of model_calls from traces for runs persisted before 2026-09-07 (app/api/schemas.py:384-402) — Violates guardrail (b). ExecutionData.model_calls is a non-null list, so historical runs would show '0 / 0' model calls in web/components/execution-performance.tsx instead of their real calls: a misleading display. Fixing that needs a nullable API field (shape change, out of scope).
- **api**: X-DocReview-Telemetry opt-in header on /review/stream (always emit stage events) — Documented public contract (docs/TUTORIAL/*/runtime.md: 'Existing clients without that header retain the default event contract'), with tests asserting the header-less stream; removal changes behaviour for current documented inputs.
- **api**: Merge admin_schemas.RetrievalProfile with review_profile.CustomRetrievalProfile — The two are distinct OpenAPI components used by the web generated types (renaming or public shape change), and the concurrent BM25 work edits CustomRetrievalProfile semantics (with_server_bm25).
- **api**: Consolidate the five identical strict BaseModel bases (StrictApiModel, StrictAdminModel, StrictProfileModel, StrictEvidenceModel, StrictOperatorModel) — Import-order constraints force the root to be review_profile.StrictProfileModel, so this becomes a ~90-reference mass rename across api/operator for a one-line config; that is renaming, not removal.
- **api**: preset_store payload.setdefault('id', path.stem) — Not legacy. Present since the store was introduced (795be89) to accept hand-copied portable preset files ('its ID must match its safe JSON filename'); shipped files already carry id. The file is also under concurrent BM25 edits.
- **api**: RetrievalService/WorkflowService/RunPersister Protocols, ApiServices Protocol, RuntimeApiServices local_inventory/scope_index/retrieval_service injection seams — Actively used by tests for injection (FakeApiServices; retrieval_service=, workflow_service=, run_persister=, scope_index= in tests/api); not injection that nobody uses.
- **api**: browser_reset_id / data/browser-reset.json capability field and the /_internal/reset runtime gate — Live. scripts/stack fresh start writes the marker and web/components/service-shell.tsx consumes it; app/operator/wipe.py drives the reset gate. (The retired /reset-local page and awaiting_browser stage belong to the operator/web lanes.)
- **api**: ReleaseGuardMiddleware keyword defaults and create_release_app(readiness_probe=, static_dir=), build_runtime_services(provider_factory=) — Used by tests/release to build guarded apps; ordinary DI, not dead options.
- **api**: RuntimeAdminApiServices.documents/document_facets pass-throughs to DocumentCatalog — Small single-caller wrappers, but tests/api/test_admin_routes.py FakeAdminServices mirrors this surface; replacing it with a catalog attribute is an internal reshape with little gain.
- **api**: GET /documents and GET /eval M5 resources — No current client, but they are documented/proxied public API resources (deploy/Caddyfile @public), not a legacy form; see ideas for a security follow-up.
- **api**: ReleaseSettings.host and canned mode — host feeds the live-admin loopback validator (behaviour); canned mode is the default offline surface used by deploy/huggingface and clean_checkout.sh.
- **agent**: Remove the DOCREVIEW_ENVIRONMENT alias of environment (app/config.py:52, app/release/config.py:66) — For ReleaseSettings it is the only init-kwarg spelling that reaches `environment`: ReleaseSettings(_env_file=None, MODE='prod', mode='runtime') fails with a literal_error on `mode` (verified), and 8+ tests use DOCREVIEW_ENVIRONMENT=. If Settings dropped it while ReleaseSettings kept it, DOCREVIEW_EN
- **agent**: Delete the `python -m app.agent` CLI and the tool-calling agent package (documented only in docs/README_archive.md) — app/agent/mcp_server.py is protected and is launched only through __main__ --mcp with registry/tools. DeterministicToolProvider also powers the CLI's default offline demo, so the package is live.
- **agent**: ProviderMetadata.default_requests before-validator (app/llm/schemas.py:399-405), used only by test builders that omit `requests` — It is a Pydantic validator on a live model, which counts as behaviour per the lane rules.
- **agent**: AgentStep StepUsage.retries (always 0) — It is part of the agent CLI's printed AgentResult JSON, so removing it changes current output for current inputs.
- **agent**: Unify the two atomic settings writers (LocalConnectionManager._persist, OpenAILimitsManager._persist) — There is no single existing definition to consolidate onto, and the error codes and messages differ. It would need a new shared helper.
- **agent**: Duplicate MAX_SEARCH_K in app/agent/__main__.py and builtin_tools.py — The duplication is intentional so `--help` answers without importing app.db and settings. The demo builds its arguments from the real model, so drift fails loudly.
- **agent**: Settings.parse_embedding_dimension validator — It is needed: pydantic rejects '384' for Literal[384] (verified), and deploy/gcp/docker-compose.deploy.yml sets EMBED_DIM: "384".
- **agent**: WorkflowRequest.system_prompt knob — It is live: app/api/runtime.py:1452 passes policy.system_prompt.
- **agent**: `state.original_query or state.query` fallbacks in workflow prompts/nodes — They are reachable: scripts/diagnostics/local_grade.py:95-105 builds WorkflowState without original_query.
- **agent**: openai-limits.json 'version': 1 check — Version 1 is the current and only format written by OpenAILimitsManager._persist, so it is not legacy.
- **agent**: Runtime isinstance TypeError guards in LLMProvider.complete / run_workflow / run_agent and the final else in _provider_failure — Python does not enforce these contracts at runtime, and tests exercise the guards, so they are not provably unreachable.
- **retrieval**: app/retrieval/__init__.py re-export facade (only tests import from the package) — AGENTS.md names app/retrieval as the one sanctioned re-export package. Removing it redesigns a public API shape, which is out of scope.
- **retrieval**: app/retrieval/_sentence_transformers.py lazy import with ImportError -> RuntimeError — sentence-transformers/torch are real optional extras (pyproject cpu/cu130/rocm). The shim keeps app.retrieval importable without them and gives an actionable error, tested in test_sbert.
- **retrieval**: tables._align reading the HTML `align` attribute ('legacy') — This handles live filing input: DART/EDGAR tables use align=, and tests plus the corpus exercise it. It is not a compatibility path for older app data.
- **retrieval**: parser.leaf_blocks 'legacy leaf table' branch — It describes layout tables in the filing HTML, which is current input, not an older app format.
- **retrieval**: app/db/bootstrap.py ensure_schema_compatibility / ensure_complete_schema — A read-only, fail-closed drift guard for the current schema. It does not repair or upgrade older databases, so it is not migration code.
- **retrieval**: ensure_bm25_stats_invalidation(schema=) parameter — The live PostgreSQL tests use it to install the trigger in isolated schemas. Removing it would break isolated live verification.
- **retrieval**: RerankProvider ABC with a single live implementation — It is the typed boundary used across api/runtime/search_consistency/service, and tests inject providers through it. Removing it would redesign an interface.
- **retrieval**: DeterministicEmbeddingProvider in `app/` code — 'deterministic' is a supported EMBEDDING_PROVIDER value and an app.cli --provider choice, so it is live configuration, not test-only code.
- **retrieval**: CrossEncoderReranker(model=, batch_size=) and SentenceTransformerEmbeddingProvider(model=, dimensions=) knobs — The factory passes sbert_model/embed_dim, and tests use these parameters as seams for fake models. Removing them trades a small cleanup for heavier test patching.
- **retrieval**: manifest.Acquisition.acquired_at Optional, SourceArtifact encoding 'euc-kr'/'cp949', role 'attachment' — No current producer emits these values, but source_artifacts CHECK constraints (models.py:79-81) mirror them. Narrowing the DB side is a schema change that trips drift detection, and tests/ingestion/seed/support.py:48 uses acquired_at=None.
- **retrieval**: dart_api cp437->cp949 member-name recovery and DECLARED_ENCODINGS decoding — This decodes live DART ZIP archives. It is not legacy app data.
- **retrieval**: source_deletion/source_selection 'legacy files require explicit cleanup' path checks — These already reject unsupported paths with a typed error, which is the target behaviour. Nothing to remove.
- **retrieval**: acquire_edgar years=None 'acquire what the manifest names' mode — corpus_admin always passes years, but tests test_edgar_api.py:347/371 use this mode to avoid discovery HTTP. Making years required means rewriting those tests with discovery mocks, which is not worth it in this pass.
- **retrieval**: seed.build_seed_batch vs parse_seed_filings + build_seed_batch_from_filings duplicate loops — They are not exactly equivalent: the progress stages differ (single 'prepare' stage vs 'parse'/'chunk'), and the admin UI shows those stages.
- **retrieval**: seed parser= injection on build_seed_batch/parse_seed_filings — Tests use it to avoid parsing real filings. It is a small, legitimate test seam.
- **evals**: public_snapshot_details._load schema_version==1 scoring-stamp reconstruction (public_snapshot_details.py:106-114) — This is not legacy. The current writer still emits RAW_ARTIFACT_SCHEMA_VERSION = 1, with an artifact config that lacks the 'scoring' stamp persist_eval_result adds to the DB row, so every current artifact takes this branch. The four deploy-bundle artifacts depend on it too.
- **evals**: public_snapshot_details._verify_bound_payload ISSUER-FYyyyy alias binding (public_snapshot_details.py:138-192) — It exists only for artifacts made before #213 (0ef82cd switched golden doc_ids from 'AMD-FY2019'-style aliases to 'sec-<accession>'). But the deploy bundle (prod-artifacts/20260909-portfolio18, four DART artifacts dated 2026-09-09) carries digests of the pre-#213 alias golden files (d1f4ab7b…, cdb35
- **evals**: GoldenRevision DB-revision paths in snapshots._create and PublicSnapshotDetails (golden_revision_id branch) — The golden_revisions table has had no writer since #206, but removing these paths changes the SnapshotCreateRequest API and DB schema (api/db lanes). The published prod snapshots' golden_revision_id values cannot be verified here (no pg_restore). Listed in ideas.
- **evals**: app/evals/crosslingual.py CLI with bilingual.py, breakdown.py and parity.py — It is documented only in docs/README_archive.md, but the current README.md advertises 'cross-lingual parity gates' as an Evaluation feature, and no current flow provides the translated arm or parity gate. It is a live feature, not a superseded CLI.
- **evals**: run.py main()/__main__ (python -m app.evals.run) — Documented only in README_archive, and nominally superseded by the Measure Matrix mode. However, the admin Matrix path always fails at ablation.run_ablation's config equality check (reproduced; see ideas), which leaves this CLI as the only working ablation-matrix runner. It also carries the budget e
- **evals**: app/evals/decomposition.py CLI (and app/agent/decompose.py make_decomposed_retriever) — This undocumented experiment harness measures a retriever used nowhere else. Removing it is a feature decision spanning the agent lane, not legacy/compat/bloat, so it is left for the user.
- **evals**: Consolidating decomposition.category_metrics onto breakdown_by_category — The two are not exactly equivalent. The dict order differs (alphabetical vs GoldenCategory declaration order in json.dumps output), and the test fixture uses id-less SimpleNamespace goldens that breakdown validation rejects. The gain is small.
- **evals**: CrosslingualArm.name 'EDGAR corpus keeps its historical names' (crosslingual.py:221-223) — Removing it would rename current artifact files for sec arms, which changes current behaviour for current inputs.
- **evals**: Historical suite ids (run --suite m3-retrieval-v1, m8-crosslingual-v1, m10-dart-crosslingual-v1, m9-decomposition-v1) — They are persisted regression-baseline keys. Renaming would silently reset baselines.
- **evals**: loader.SourceMissingError subclass — Its type is observable. The admin matrix job records error_code = type(error).__name__.lower(), so collapsing it into GoldenDataError changes job records.
- **evals**: loader docreview-golden-set envelope unwrap — This is the current user-dataset file format (golden_admin._write writes it; docs/TUTORIAL en/ko document it) and it is accepted by the CLIs. It is kept inside evals-c05.
- **evals**: EvaluationAdminService._hydrate_jobs skip of unreadable persisted requests — This tolerant path keeps startup recovery from crashing on unreadable rows. Removing it would turn a harmless ignore into a crash (fails guardrail b).
- **evals**: admin._quick_retriever `profile.lexical_ranker or "ts_rank_cd"` — The fallback is unreachable at runtime (a reranker requires hybrid, which requires a ranker), but it provides the type narrowing retrieve() needs. An assert or cast would not be simpler.
- **evals**: Inline admin._corpus_fingerprint (single-caller pass-through, admin.py:756 at HEAD) — The gain is trivial, and app/evals/admin.py plus tests/evals/test_admin.py currently have foreign uncommitted edits in the working tree (server BM25 profile work). Avoided to prevent collisions.
- **evals**: clock= injection parameters (measure_query_budget, evaluate_retriever, temporary_corpus_session) — These are legitimate time-injection seams that tests use for deterministic budgets, not configuration nobody sets.
- **ops**: rag-alias.sh retire loop for previously owned command names (lines 10-20) and unalias of alias-named commands (28-31) — This is the generic helper update lifecycle, tested with a synthetic rag-obsolete name. Removing the unalias would break the function definitions whenever the user already has an alias with the same name. Neither handles a legacy data format.
- **ops**: StepTrace.default_requests validator (app/observability/types.py:83-90) — It is a Pydantic validator on a live model, and test support builds StepTrace without requests, so this is behaviour rather than bloat.
- **ops**: review_usage fallbacks to Trace rows / matched-trace cost when model_calls are missing or unpriced (app/observability/usage.py:250-333) — These read runs that older code persisted in users' databases. Removing them would change usage totals for existing rows.
- **ops**: stored_progress returning None for refs without operation_progress_v1 (app/operator/progress.py:39-58) — Current job kinds outside _PHASES also produce refs without progress.
- **ops**: 'detail' key in operator wipe_failure (app/operator/service.py:310-318, docstring says legacy) — The current web operatorRequest reads payload.detail (web/lib/operator-api.ts:64-66). Only the docstring wording is stale.
- **ops**: docker/docker-compose.dev.yml no-op overlay — AGENTS.md (protected) names the dev/prod overlays as the local contract. compose_command and WipeService._compose also pass it explicitly.
- **ops**: Compose ps JSON-array branch in scripts/stack/quickstart.py:219-223 and scripts/schema/recreate.py:53-57 — The array branch is dead behind quickstart's Docker Compose ≥2.24.4 gate. The recreate path (`rag-dev reset data`) has no version gate, though, and would crash with a TypeError on array output. Filed under ideas instead.
- **ops**: deploy/huggingface Space assets and the clean_checkout.sh canned HF smoke — Whether to retire this deployment target is an owner decision. The clean-checkout gate still builds the image, and tests/release/test_03_release_assets.py checks the assets. Its README points to a nonexistent docs/en/m7-deployment (see ideas).
- **ops**: Duplicated deploy/gcp and deploy/oracle scripts (apply_backend.sh, print_origin.sh, deploy_env_config.sh) — The Oracle target was only just added on main (cc2d7c2). Merging the two sets would redesign the deploy tooling, and deploy changes need separate authorisation.
- **ops**: RuntimeCorpusAdminService in-memory job path when job_store is None — public_portfolio and the release readiness fallback construct the service without a job store. Removing the path would be a redesign.
- **ops**: app.cli ingest vs rag-dev corpus ingest_manifest — The current tutorial documents both (docs/TUTORIAL/en/cli.md:335).
- **ops**: AdminCommand.__post_init__ re-validation duplicating CorpusOperationRequest validators — It also validates commands restored from persisted job JSON (_command_from_stored), so it is not a pure duplicate.
- **ops**: scripts/schema/sources.py 'inputs' namespace — Live: app/ingestion/source_selection.py:241 pins inputs/<registry>/...
- **ops**: LifecycleReceipt.restarted optional field — It still reads start-fresh receipts written by earlier runs, and it is harmless after ops-c02 because restarted is always False.
- **ops**: DOCREVIEW_ENVIRONMENT fallback in scripts/diagnostics/local_grade.py:298 — It must match app/config.py AliasChoices('MODE','DOCREVIEW_ENVIRONMENT') (config lane). Removing it only in the script would let the benchmark run while the app treats DOCREVIEW_ENVIRONMENT=prod as the public deployment.
- **web**: web/lib/storage.ts versionedKey/readProductionValue migration of unversioned keys (docreview.locale, docreview:theme, docreview:layout:*, docreview:reading:*) to :v1 envelopes, and version-0 entries in validateBrowserSettings — Current code still produces these keys. LOCALE_KEY and THEME_KEY are unversioned names, DEV storage and the pre-configureBrowserStorage raw path write them as-is, and exports can contain version-0 keys when a PROD migration write fails.
- **web**: browserThemeBootstrap(legacyKey) in web/lib/storage.ts:572 — Only the parameter name says legacy. The caller passes the current THEME_KEY.
- **web**: docreview:preview: carve-out in ownedStorageKey (web/lib/storage.ts:279) — The comment records an explicit decision to keep archived preview records for a future release. Removing the carve-out would make leftover preview keys raise 'version' storage warnings and move their bytes into recovery on PROD, so current behaviour changes.
- **web**: failureReport legacy budget-line regex (web/lib/pipeline.ts:563-567) — Still has a current producer: app/workflow/runner.py:139-144 emits ProviderFailure(status='budget_exceeded') with only the 'which: used=… limit=…' details line and no `budget` object.
- **web**: execution-performance providerTimings `provider_timing ?? local_timings` fallback — Still has a current producer: app/api/schemas.py:399-412 serializes both local_timings and provider_timing.
- **web**: evaluationDataset admin_identity / root golden_sha256 fallbacks (web/lib/evaluation-labels.ts:17-30) — The backend still writes admin_identity (app/evals/admin.py:920) and reads the root golden_sha256 (app/evals/snapshots.py:73-76), and old evaluation rows live in the user's DB. This is not a web-only legacy path.
- **web**: parseNavigationUrl returning null for URLs without ?view (web/lib/navigation.ts:24-28) — The bare root URL is the current landing page, not a legacy form.
- **web**: /docs/ and /docs/cli/ locale-less DocumentationRedirect pages — Both were added with the localized routes in 1dd72a7 as locale-negotiating entry points. They are not compatibility shims for a retired URL.
- **web**: mergeProfile in loadDefaultProfile/migrateConversation — It fills fields added after a record was saved, for example local_model (storage.test 'restores old conversation profiles without a model'). Removing it would pass undefined fields into rendering and requests.
- **web**: answerEngineStates `openai.model ?? active_review_model` and pipeline answerModelDraft model fallbacks — Both fields are current and equal in /ready. Removing the fallback saves nothing and is not legacy.
- **web**: getDocumentFacets `sections ?? []` normalization (web/lib/api.ts:451,459) — The generated type marks sections optional because the backend field has a default (admin_schemas.py:533). Removing the normalization needs the backend field made required first.
- **web**: operations.tsx 'Target not reported' fallback for commands without target — Tiny, and removing it would render t(undefined) for a malformed response instead of a typed notice. Low value.
- **web**: TOUR_TARGETS export used only by tests (web/components/onboarding.tsx:37) — It is a one-line derivation of the live STEPS data. Moving it into tests would require exporting STEPS or reproducing the STEPS data logic in the tests, which AGENTS.md forbids.
- **web**: useNotificationCenter vs useNotifications (web/components/notifications.tsx:117-119) — They are deliberately separate typed facades, the narrow Notifications interface and the full outlet context, not duplicate logic.
- **web**: Focus-trap effects in measure-workspace.tsx:153-168 and public-evaluation-workspace.tsx:68-84 — Not exactly equivalent (different initial focus target and control selectors), and consolidating them needs a new shared module, which is out of scope.
- **web**: clearDocReviewBrowserData (wipe-runtime.tsx) vs applyFreshStartReset (storage.ts) — Different semantics: the wipe keeps the locale key, and the fresh start honours the preview carve-out and receipts. Consolidating would change current behaviour.
- **web**: JobProgress 'Progress not reported' for jobs without stage data — Queued and current jobs also reach this state, so it is not legacy-only.
- **web**: review-progress `path_decision?.resolved_scope ?? event.resolved_scope` — The backend emits both fields (app/api/runtime.py:770,1615-1624).
- **web**: heading-alias markers (web/lib/tutorial-structure.mjs, tutorial-markdown.mjs) — Used by more than 90 markers across current docs/TUTORIAL files, some possibly as live link targets. That is a docs-content decision, not a web-only removal.
- **dup**: Move the duplicated OpenAI key-slot fields, the resolve_openai_key_slot validator, the openai_api_key/openai_key_slot properties, the seven local_llm_* fields and blank_local_numbers_use_defaults from Settings (app/config.py:48-60, 86-118, 136-176) and ReleaseSettings (app/release/config.py:64-120, 121-167) into their shared base DotenvFirstSettings (app/settings_sources.py) — Not equivalent. Base-class fields come before subclass fields, and that reorder changes alias resolution. In a scratch test, ReleaseSettings(mode="runtime") failed with "Input should be 'dev' or 'prod'" because the kwarg bound to environment's case-insensitive MODE alias, and 73 settings/API tests f
- **dup**: Atomic JSON/bytes writers: Manifest.write (app/ingestion/manifest.py:252-265), publish_bytes (app/ingestion/acquisition.py:65-84), GoldenAdmin._write, LocalConnectionManager._persist (app/llm/local_connection.py:238-265), OpenAILimitsManager._persist (app/llm/openai_limits.py:201-229), PresetStore save, JobHistory._write_backup, wipe._persist, scripts/schema/sources.save — They differ in file mode (0o664, 0o640, mkstemp 0o600), directory fsync, cleanup semantics, text vs binary, and error translation into domain codes and messages. No existing generic function covers them: publish_bytes adds corpus-root confinement, so Manifest.write cannot call it. The closest pair,
- **dup**: Canonical JSON dumps helpers: workflow/prompts._dumps, api/evidence._canonical_json, evals/index_identity._encode, regression config dumps, observability/trace, evals/snapshots._hash_rows — These are one-line json.dumps calls in unrelated packages with different allow_nan/default=str/encode choices. Consolidating adds cross-package coupling for no real saving, and some variants are not equivalent.
- **dup**: BM25 parameter validation in retrieval/bm25._validated_parameters, evals/arms (bm25_parameters), retrieval/service.retrieve and retrieval/__main__ — Messages differ ("k1 must..." vs "bm25_k1 must..."), as do bool/None handling and when the check applies (only for bm25 arms), so this is not exactly equivalent.
- **dup**: Duplicate usage/span/label validators on StepUsage, RawProviderResponse, StepTrace, ProviderTurn and the workflow/api/agent citation models — Pydantic validators on distinct live models are behaviour. Sharing them would need a new mixin or base class, which is a redesign, and StepTrace's version carries extra request rules.
- **dup**: percentile in scripts/diagnostics/readiness.py:38 vs nested percentile in app/evals/measurement.py:177 — Different rank formulas (round vs ceil) and empty handling (0.0 vs ValueError), so they are not equivalent.
- **dup**: Admin retrieval execution: RuntimeAdminApiServices._retrieve_profile (app/api/admin_runtime.py ~784-845) vs EvaluationAdminService retriever building (app/evals/admin.py ~766-805) — Similar argument lists, but different control flow and return types: RetrievalResult with component rankings vs a Retriever. They also differ in reranker and ts_rank_cd defaulting. No single existing function is equivalent.
- **dup**: Query-routing loops in RuntimeApiServices.retrieve (~925-950) and review (~1425-1445) — They obtain the provider and budget differently and one reuses snapshot routing; consolidation needs a new helper and a behaviour audit.
- **dup**: Public vs admin document_inventory route handlers (app/api/routes/public_documents.py:20-60, app/api/routes/admin.py:83-120) — These are thin API-surface declarations. Merging them or swapping the inline sort Literal for DocumentSort risks changing the OpenAPI contract, which is out of scope.
- **dup**: Docker host pinning in scripts/schema/recreate.local_target (37-45) and scripts/stack/fresh.docker_inventory (180-191) — Error messages differ (Recreate vs Fresh start, split socket checks) and no existing shared function exists, so consolidation would change user-facing text.
- **dup**: _projected_input_tokens one-liners on OpenAILLMProvider (app/llm/provider.py:611) and LocalLLMProvider (app/llm/local.py:57) — The base class deliberately returns None for deterministic fixtures, so sharing needs an intermediate class. Two one-line overrides are not bloat.
- **dup**: classify_placement in scripts/diagnostics/local_grade.py:108 vs app/llm/local_inventory._placement — Outputs differ ("unknown" vs None) and validity checks differ (no negative or zero checks in the script), so they are not equivalent.
- **dup**: release/secrets.redact_text vs observability redact_sensitive_text — The log filter intentionally does only exact-secret replacement on formatted records; the persistence helper also applies credential patterns. The semantics differ.
- **dup**: _loopback_host (app/release/config.py:33) vs middleware origin host check (app/release/middleware.py:140-142) — Different normalization (strip/lower) and exception handling; not equivalent.
- **dup**: forget_history on CorpusAdminService (app/corpus_admin.py:949) and EvaluationAdminService (app/evals/admin.py ~595) — These are methods on two unrelated service classes. Sharing them needs a new base class or mixin, which is a redesign.
- **dup**: translation_boundary (app/evals/crosslingual.py:839) vs decomposition_boundary (app/evals/decomposition.py:206) beyond the pricing copy covered by dup-c01 — Different roles, token constants and settings source (explicit arg vs get_settings); no single existing function fits.
- **tests-support**: Replace the parser_module / edgar_module / xref_module import_module fixtures (tests/ingestion/conftest.py:15-30) with direct imports — These fixtures once carried a sys.path shim (ab2c23b), but it is already gone. Today they only return fixed modules. Replacing them means about 280 mechanical edits across roughly 12 files for no behaviour gain, which is out of proportion for this pass.
- **tests-support**: XREF_TABLES / XREF_ITEM_SHAPE baselines in tests/ingestion/golden.py and the always-skipped tests/ingestion/test_04_xref_page_join.py — These are not legacy. Intel filings are in app/ingestion/source_catalog.py, data/profiles/INTC.json and docs/TUTORIAL quickstart-dev, so an operator can widen the corpus and the xref baselines become active again. Judging dormant tests belongs to the coverage pass.
- **tests-support**: fake_sentence_transformers in tests/retrieval/support.py — sentence-transformers is a real optional extra, imported lazily through app/retrieval/_sentence_transformers.py. Faking the module is required to test that live path without the heavy package installed.
- **tests-support**: _isolated_public_allowance autouse fixture (tests/conftest.py:11-17) — DOCREVIEW_PUBLIC_ALLOWANCE_PATH is live: ReleaseSettings.public_allowance_path uses env_prefix DOCREVIEW_ (app/release/config.py:47,81), and deploy/gcp/docker-compose.deploy.yml:45 sets it.
- **tests-support**: --require-live-postgres option and DOCREVIEW_EXPECT_LIVE_POSTGRES env (tests/conftest.py, tests/live_postgres.py) — This is the current live-gate contract, used by AGENTS.md, deploy/docker-compose.md, app/operator/commands.py:83 and scripts/release/clean_checkout.sh:45,79.
- **tests-support**: executable/command_log helpers and launcher fixtures duplicated in tests/scripts/deploy/test_gcp_backend.py and test_gcp_setup.py — executable and command_log are identical, but tests/scripts/deploy has no support module or __init__, so consolidating needs a new module, which this pass does not allow. The launcher fixtures differ (copied scripts, dotenv keys, bundle dependency).
- **tests-support**: Duplicated ceiling() in tests/llm/test_openai_limits.py:14 and tests/api/test_08_openai_limits.py:50 — The two are identical, but no existing support module fits: there is no tests/llm/support.py and tests/api has only conftest.py. Consolidating needs a new module or an unrelated cross-package home.
- **tests-support**: Unify the many ChunkHit builders (api conftest hit fixture, workflow support hit, evals support relevant_hit, test_ablation/test_scoring/test_crosslingual/test_evidence local hit) — They differ in doc ids, bodies, spans, citations and scores, so replacing one with another is not exactly equivalent. Only the agent copy (c03) is exact.
- **tests-support**: Unify the budget() helpers in tests/llm/test_local.py, tests/llm/test_provider.py, tests/agent/test_decompose.py, tests/retrieval/test_translate.py and provider_budget in tests/api/test_06_review_lifecycle.py — They use different limits and prices (zero-cost, 0.4/1.6 versus 2/10, different max_output), so they are scenario data, not the same logic.
- **tests-support**: Shared prologue of _exercise_live_postgres in tests/evals/test_regression.py, tests/observability/test_01_run_persistence.py and tests/retrieval/test_01_postgres_retrieval.py — They are not exactly equivalent: timeouts differ (3s vs 5s), the caught exception sets differ, and the setup steps differ (SELECT 1 vs ensure_vector_extension). The rest of each is scenario-specific.
- **tests-support**: Rebuild the api conftest trace/successful_run/budget_run fixtures on tests/observability/support builders — Every field would still be overridden, so there is no reduction. The values differ from the observability defaults.
- **tests-support**: Consolidate SOURCE_SHA256 across packages (workflow, seed, retrieval, evals supports, agent/test_loop.py, the chunk support literal) — Cross-package imports for a one-line constant would add coupling between test areas. Only the intra-package evals duplicates are proposed (c05).
- **tests-support**: Manifest-missing skip in the ingestion conftest manifest fixture — This is harmless defensive test setup, not a compatibility path. data/corpus/manifest.json is tracked, so the branch is inert rather than a legacy format.
- **tests-support**: Unused fixtures or support names — None found. Every conftest fixture has at least one requesting test within its scope, and every support/golden name has an importer or internal use.

## Tests removed in round 1

Source: the `tests_only_covering` lists of the applied round-1 candidates in `wf1.json`, the
`test_edits` of the round-1 editors in `wf2.json`, and `git diff main..HEAD -- tests web`
(only tests whose removal is committed on the branch appear here). "Kept test covering the same
behaviour" names the surviving test the editor pointed at, or `none needed` when the deleted test
covered only the deleted code.

| test (file::name) | reason | kept test covering the same behaviour |
|---|---|---|
| `tests/workflow/test_runner.py::test_the_session_retriever_forwards_every_ranking_knob_it_was_bound_with[True]` | covered only the deleted `make_session_retriever` (agent-02); file deleted in `ae61683` | `run_workflow` stays covered by `tests/workflow/test_01_node_guardrails.py`, `test_02_run_lifecycle.py`, `test_03_live_openai_smoke.py` |
| `tests/workflow/test_runner.py::test_the_session_retriever_forwards_every_ranking_knob_it_was_bound_with[False]` | same as above | same as above |
| `tests/workflow/test_runner.py::test_the_session_retriever_widens_the_candidate_pool_to_the_overfetched_k` | same as above | `tests/workflow/test_02_run_lifecycle.py` (evidence over-fetch through `evidence_fetch_k`) |
| `tests/retrieval/test_hybrid.py::test_hybrid_search_injects_filters_and_fuses_sequential_candidate_lists` | covered only the deleted `hybrid.hybrid_search` (retrieval-02) | the four `test_rrf_*` tests in the same file still cover `fuse_ranked_lists` |
| `tests/retrieval/test_hybrid.py::test_hybrid_search_supplies_default_filters_and_validates_inputs` | same as above | same as above |
| `tests/ingestion/test_registry.py::test_missing_registry_never_defaults_to_sec` | asserted only that the deleted `resolve_registry` wrapper raises `AttributeError` on a dict (retrieval-17) | `tests/ingestion/test_registry.py::test_explicit_source_selects_the_registered_parser` (now calls `registry_for` directly) |
| `tests/evals/test_curation.py` (17 tests, whole file) | covered only the deleted `app/evals/curation.py` (evals-01) | none needed |
| `tests/evals/test_04_committed_candidate_intake.py::test_committed_candidates_pass_every_machine_gate_and_stay_pending` | ran the deleted candidate batch through the deleted curation intake (evals-01) | none needed; `tests/evals/test_01_golden_corpus_binding.py` keeps the `MAX_ANSWER_SPAN_CHARS` width check with the literal `2_500` |
| `tests/evals/test_breakdown.py::test_breakdown_markdown_renders_the_exact_table` | its table assertion and two `ValueError` checks covered only the deleted `breakdown_markdown` (evals-05); renamed, not dropped | renamed to `test_breakdown_by_category_ignores_score_order`, which keeps the live `breakdown_by_category` assertion |
| `tests/observability/test_cost.py::test_cost_estimation_is_exact_accumulative_and_fail_closed` | covered the deleted `app/observability/cost.py` (ops-02); its `TokenPricing.estimate` arithmetic moved | `tests/llm/test_schemas.py::test_token_pricing_charges_cached_and_cache_write_input_at_policy_prices` (same inputs and expected values 14.00, 13.69, 0) |
| `tests/observability/test_cost.py::test_trace_cost_totals_what_the_provider_charged_rather_than_repricing` | covered only the deleted `estimate_trace_cost_usd` | none needed |
| `tests/observability/test_cost.py::test_pinned_price_table_cannot_be_mutated_by_a_consumer` | covered only the deleted `MODEL_PRICES` table | none needed; prices are pinned in `app/openai_models.py` and read by `tests/test_openai_models.py` |
| `tests/test_corpus_admin.py::test_canned_snapshot_is_read_only_filterable_and_db_free` | covered only the deleted `CannedCorpusAdminService` (ops-04) | none needed |
| `tests/test_corpus_admin.py::test_canned_service_refuses_every_operation` | same as above | none needed |
| `web/components/review-progress.test.tsx :: keeps the three real count segments` | called only the deleted `progressCountsLabel` (web-05) | none needed |
| `web/lib/preparation-navigation.test.ts :: chooses the earliest verified prerequisite` | exercised only the deleted `preparationTarget` (web-06) | `routes only typed source absence to acquisition` (same file) still covers the live `preparationErrorTarget` |
| `web/lib/preparation-navigation.test.ts :: keeps unknown infrastructure causes in setup diagnosis` | same as above | same as above |

Round-1 tests that were rewritten rather than removed (assertions kept, call retargeted to the
surviving function): `tests/retrieval/test_hybrid.py::test_rrf_*` (four tests, `rrf_fuse` ->
`fuse_ranked_lists`), `tests/retrieval/test_service.py::test_package_exports_the_complete_production_surface`
(dropped `hybrid_search` and `rrf_fuse` from the expected `__all__`),
`tests/ingestion/test_parser.py::test_read_source_preserves_crlf_for_source_offsets` (renamed
`test_decoded_source_preserves_crlf_for_source_offsets`, reads the bytes inline),
`tests/ingestion/test_tables.py` caption tests (`table_captions(html)` -> `render_table(html)[0]`,
later retargeted again in round 2), `tests/ingestion/test_06_dart_parsing.py` fixture
(`resolve_registry` -> `registry_for`), `tests/test_openai_models.py::test_translation_allows_only_luna_and_terra_and_snapshot_is_public`
(reads `_ALLOWED`/`_DEFAULTS` directly), `web/lib/i18n.test.tsx` (calls
`localizedDocumentationRoute` directly).

## Tests removed in round 2

Source: the `tests_removed` lists of the accepted round-2 candidates in `wf3.json`, the
`test_edits` of the editors in `wf4_partial.json` and `wf5.json`, the final commit `c3975cc`,
and `git diff main..HEAD -- tests web`.

| test (file::name) | reason | kept test covering the same behaviour |
|---|---|---|
| `tests/api/test_02_ingest_review.py::test_ingest_route_completes_synchronously` | `POST /ingest` removed (api-c01) | ingestion is covered through the corpus job path in `tests/test_corpus_admin.py` |
| `tests/api/test_02_ingest_review.py::test_missing_manifest_is_a_typed_client_error` | same | `tests/test_corpus_admin.py` (manifest validation of `AdminCommand`) |
| `tests/api/test_06_review_lifecycle.py::test_runtime_prepares_ingestion_off_the_event_loop` | `RuntimeApiServices.ingest` removed (api-c01) | none needed |
| `tests/api/test_06_review_lifecycle.py::test_ingest_confines_manifests_to_the_corpus_directory` | `_resolve_manifest_path` removed (api-c01) | none needed |
| `tests/api/test_runtime.py::test_ingest_forwards_selection_and_model_planning_provider` | same | none needed |
| `tests/api/test_schemas.py::test_ingest_and_review_requests_reject_empty_bodies` | `IngestRequest` removed; renamed | `test_review_request_rejects_an_empty_body` keeps the `ReviewRequest` half |
| `tests/release/test_01_request_guards.py::test_public_ingestion_is_disabled_before_service_execution` | the `/ingest` 403 guard removed (api-c01 remainder, `c3975cc`) | `POST /ingest` now falls to the typed 404 `route_not_found`; `tests/api/test_03_route_surface.py` pins the route set |
| `tests/release/test_01_request_guards.py::test_local_operator_bypasses_public_rate_limit_but_not_ingest_guard` | renamed; ingest assertion dropped | `test_local_operator_bypasses_public_rate_limit` keeps the rate-limit bypass assertions |
| `tests/release/test_01_request_guards.py::test_public_prompt_budget_local_and_snapshot_controls_stay_locked` | top-level `budget` case removed (api-c05, `c3975cc`); renamed | `test_public_prompt_local_and_snapshot_controls_stay_locked` keeps the prompt-policy, local-engine and snapshot cases |
| `tests/api/test_07_local_connection.py::test_legacy_review_limits_cannot_bypass_public_controls` | top-level `budget`/`max_context_chars` are no longer a public-lock case (api-c05) | `test_retired_top_level_review_limits_are_rejected_as_unknown_fields` (same parametrization; expects 422 `extra_forbidden`) |
| `tests/release/test_middleware.py::test_control_denial_preserves_route_validation_ownership` | re-parametrized over `profile` only (payload-only cases gone) | same test name, profile cases kept |
| `tests/api/test_05_runtime_topology.py::test_runtime_factory_is_import_safe_and_creates_distinct_apps` | `app.main` removed (api-c04) | `test_runtime_import_does_not_build_the_database_engine` retargeted to `import app.api.runtime` |
| `tests/api/test_05_runtime_topology.py::test_health_route_reports_process_liveness_without_external_services` | `app.main` `/health` removed | the release app's `/health` is covered by `tests/release/test_02_release_app.py` |
| `tests/api/test_06_review_lifecycle.py::test_build_runtime_services_composes_from_settings` | `app.api.runtime.build_runtime_services` removed (api-c04); its earlier BM25/ranker assertions were vacuous | `tests/release/test_02_release_app.py::test_runtime_composition_serves_the_configured_bm25_settings` |
| `tests/test_cli.py::test_serve_passes_every_runtime_option_to_uvicorn` | `app.cli serve` removed (ops-c10) | `test_python_module_entrypoint_exposes_all_commands` and the help tests assert `{retrieve,ingest}` |
| `tests/release/test_config.py::test_manual_release_prices_are_rejected` | tombstone fields removed (api-c06) | none needed |
| `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[*-connection]`, `[*-reset]` (6 cases) | routes removed (api-c02, agent-c03) | the `disconnect`, `servers`, `select`, `diagnostics` cases remain |
| `tests/api/test_07_local_connection.py::test_connection_routes_save_disconnect_reset_and_preserve_failed_candidate` | renamed; restore now goes through `POST /select {"server_id": "default"}` | `test_connection_routes_save_disconnect_restore_default_and_preserve_failed_candidate` |
| `tests/api/test_07_local_connection.py::test_named_server_and_diagnostic_routes_preserve_existing_clients_and_selection` | renamed; legacy-save assertion removed | `test_named_server_and_diagnostic_routes_preserve_the_selection` |
| `tests/llm/test_provider.py::test_legacy_flag_keeps_the_sdk_parsed_path` | `structured_output=False` path removed (agent-c01) | `test_openai_adapter_sends_one_schema_bound_request_with_injected_offline_client` (strict `text.format` check tightened) |
| `tests/llm/test_estimate.py::test_projection_is_refused_only_when_it_exceeds_the_allowance` | `exceeds_allowance` inlined (agent-c12) | `tests/llm/test_provider.py::test_projection_equal_to_the_allowance_is_sent_and_one_token_over_is_refused` |
| `tests/llm/test_local_engine.py::test_provider_carries_the_configured_timeout_and_refuses_a_nonpositive_one` | `build_local_provider` inlined (agent-c15); moved | same name in `tests/llm/test_local.py` (constructs `LocalLLMProvider` with `protocol="ollama"`) |
| `tests/llm/test_local_engine.py::test_provider_carries_the_configured_context_window_and_refuses_a_nonpositive_one` | same | same name in `tests/llm/test_local.py` |
| `tests/agent/test_provider.py::test_openai_adapter_wires_base_url_and_disables_hidden_sdk_retries` | `base_url` knob removed (agent-c11); renamed | `test_openai_adapter_disables_hidden_sdk_retries_and_records_the_client_url` |
| `tests/ingestion/test_tables.py::test_empty_rows_and_columns_are_removed` | legacy markdown renderer removed (retrieval-c01) | `structured_table(...).render()` assertions in the same file, `tests/ingestion/test_05_table_rendering.py` and `tests/ingestion/chunk/test_03_tables.py` |
| `tests/ingestion/test_tables.py::test_rows_wider_than_the_header_keep_every_cell` | same | same |
| `tests/ingestion/test_tables.py::test_render_table_serves_both_answers_from_one_parse` | same | same |
| `tests/ingestion/test_tables.py::test_data_table_keeps_captions_inline_and_reports_none` | renamed | `test_data_table_keeps_captions_inline` (asserts the inline caption prefix) |
| `tests/ingestion/test_02_corpus_parsing.py::test_parsed_result_carries_the_original_measurements` | `ParsedFiling.n_blocks/n_chars` removed (retrieval-c05) | `test_document_coverage_matches_golden` now measures from the leaf blocks |
| `tests/ingestion/test_edgar_api.py::test_year_range_covers_both_bounds` (2 cases) | `parse_years` removed with the CLI (retrieval-c02) | none needed |
| `tests/ingestion/test_edgar_api.py::test_unusable_year_range_is_rejected` (6 cases) | same | none needed |
| `tests/ingestion/test_edgar_api.py::test_ticker_filter_is_case_insensitive` | `pending(tickers=)` CLI-only knob removed | none needed |
| `tests/ingestion/test_progress.py::test_byte_bar_scales_bytes_and_clears_itself` | `byte_bar` removed (retrieval-c02) | `test_operation_bar_tracks_absolute_multi_stage_updates` keeps the live `operation_bar` |
| `tests/ingestion/test_progress.py::test_declared_length_becomes_the_total` | same | same |
| `tests/ingestion/test_progress.py::test_an_undeclared_length_leaves_the_bar_open_ended` | same | same |
| `tests/ingestion/test_progress.py::test_a_retry_rewinds_the_bar_instead_of_double_counting` | same | same |
| `tests/ingestion/test_progress.py::test_overall_bar_counts_items_and_labels_the_position` | `overall_bar` removed | same |
| `tests/ingestion/test_progress.py::test_a_line_printed_during_a_run_goes_through_the_bar` | same | same |
| `tests/retrieval/test_service.py::test_cli_acceptance_arguments_and_payload_keep_component_scores_private` | `python -m app.retrieval` removed (retrieval-c03) | `tests/test_cli.py` covers `app.cli retrieve`; component-score privacy stays in `test_service.py` retrieve tests |
| `tests/retrieval/test_service.py::test_cli_rejects_invalid_bm25_overrides_during_argument_parsing` (8 cases) | same | BM25 parameter validation is covered by `tests/retrieval/test_bm25.py` |
| `tests/retrieval/test_service.py::test_cli_resolves_language_routing_from_settings_and_honours_an_override` (4 cases) | same | not replaced; an `app.cli retrieve` routing test was suggested as a follow-up |
| `tests/retrieval/test_bm25.py::test_cli_exposes_the_ranker_flags` | same | none needed |
| `tests/retrieval/test_bm25.py::test_cli_defaults_leave_every_ranker_override_unset` | same | none needed |
| `tests/retrieval/test_cross_encoder.py::test_cli_accepts_rerank_flag` | same | none needed |
| `tests/retrieval/test_cross_encoder.py::test_run_passes_cross_encoder_when_rerank_is_enabled` | same | reranker wiring is covered by `tests/api/test_06_review_lifecycle.py` and `tests/retrieval/test_rerank.py` |
| `tests/retrieval/test_sbert.py::test_cli_accepts_sbert_provider` | same | none needed |
| `tests/retrieval/test_rerank.py::test_no_provider_keeps_shared_deterministic_order_and_truncates` | provider-less branch removed (retrieval-c06) | `test_reranking_rejects_blank_queries_and_negative_limits` (stub provider that must not be called) |
| `tests/retrieval/test_korean.py::test_grams_must_be_positive` | `grams` knob removed (retrieval-c08) | the remaining tokenizer tests pin the 2-gram output |
| `tests/evals/test_scoring.py::test_empty_suite_is_rejected[recall_at_k|hit_rate_at_k|mrr]` | wrappers removed (evals-c06) | `test_empty_suite_is_rejected` is now a plain `score_suite([])` test |
| `tests/evals/test_regression.py::test_tolerances_accept_a_partial_metric_mapping` | mapping coercion removed (evals-c12); renamed | `test_tolerances_accept_a_partial_metric_set` (uses `RegressionTolerances(mrr=0.01)`) |
| `tests/evals/test_regression.py::test_tolerances_reject_metrics_without_an_explicit_direction` | unknown-key validation of raw mappings removed | none needed (the type carries the metric set) |
| `tests/scripts/schema/test_status.py::test_schema_preparation_uses_shared_startup_contract` | `status.prepare_schema` now is `app.db.startup.prepare` (dup-c08) | `tests/db/test_startup.py::test_prepare_uses_the_shared_bootstrap_and_releases_its_engine` |
| `tests/operator/test_wipe.py::test_extreme_*` (7 tests) and `test_browser_acknowledgement_is_operation_bound` | extreme wipe removed (ops-c01) | `test_symlink_and_changed_file_fail_closed` (retargeted from the extreme variant) keeps change detection and symlink refusal |
| `tests/operator/test_service.py::test_browser_ack_requires_auth_and_matching_reset` | `POST /wipe/browser-cleared` removed | auth coverage remains in the other `tests/operator/test_service.py` route tests |
| `tests/operator/test_commands.py::test_markdown_renderer_is_derived_from_the_registry` | renderer moved into the test (ops-c12) | `test_readme_command_table_matches_the_executable_registry` (uses the local `_render_commands_markdown`) |
| `tests/scripts/stack/test_fresh.py::test_clean_restores_data_and_preserves_configuration_with_own_receipt` | multi-mode `start_fresh` collapsed (ops-c02) | its preview-format, status and preserved-path assertions moved into `test_environment_reset_preserves_dirty_and_untracked_source_work` |
| `tests/scripts/stack/test_fresh.py::test_extreme_removes_environment_but_retains_template_and_never_starts` | same | none needed |
| `tests/scripts/stack/test_fresh.py::test_tracked_code_requires_explicit_discard_and_preview` | same | none needed |
| `tests/scripts/stack/test_fresh.py::test_index_changes_cannot_cancel_worktree_guard` | reworked | `test_environment_reset_preserves_staged_changes` |
| `tests/scripts/stack/test_fresh.py::test_post_preview_git_changes_are_preserved_before_restore[worktree|index|head]` | same | none needed |
| `tests/scripts/stack/test_stack_commands.py::test_extreme_*` (`_confirmation_cancellation_never_submits` 4 cases, `_success_reports_scope_without_restart`, `_eof_before_both_gates_never_submits` 2 cases) | same | none needed |
| `tests/scripts/stack/test_stack_commands.py::test_extreme_completion_does_not_claim_browser_deletion` | renamed | `test_completion_does_not_claim_browser_deletion` |
| `tests/scripts/stack/test_stack_commands.py::test_extreme_plain_warning_and_noninteractive_guard` | renamed | `test_plain_warning_and_noninteractive_guard` |
| `tests/scripts/stack/test_stack_commands.py::test_rejection_uses_only_allowlisted_diagnostics` | wipe-preview rejection mapping removed (ops-c04); renamed | `test_rejection_uses_only_the_generic_message` |
| `tests/scripts/stack/test_stack_commands.py::test_normal_clean_start_uses_host_scope_without_web_preview` | `scripts.stack.commands reset` removed (ops-c03) | none needed |
| `tests/scripts/stack/test_stack_commands.py::test_noninteractive_reset_does_not_request_preview` | same | none needed |
| `tests/scripts/stack/test_stack_commands.py::test_host_setup_failure_is_not_reported_as_success` | same | none needed |
| `tests/scripts/stack/test_stack_commands.py::test_host_database_failure_is_reported_without_sql_disclosure` | same | none needed |
| `tests/scripts/stack/test_stack_commands.py::test_host_interruption_points_to_schema_state_without_claiming_operator_evidence` | same | none needed |
| `tests/scripts/stack/test_stack_commands.py::test_host_receipt_failure_is_not_overridden_by_older_web_success` | `reset_status` no longer reads the host receipt | `test_status_is_read_only_without_configuration` keeps the operator-evidence status |
| `tests/scripts/stack/test_quickstart.py::test_host_clean_start_waits_for_verified_reset_before_starting` (3 cases) | quickstart reset mode removed (ops-c03) | none needed |
| `tests/scripts/stack/test_quickstart.py::test_startup_failure_after_reset_cannot_repeat_deletion_or_print_ready` | same | none needed |
| `tests/scripts/schema/test_recreate.py::test_successful_reset_reports_the_callers_restart_intent[False|True]` | `restart_planned` removed; renamed | `test_successful_reset_leaves_the_api_stopped` |
| `tests/scripts/diagnostics/test_ollama.py` (10 tests: `test_healthy_unloaded_answer_model_is_available_without_a_load`, `test_diagnosis_uses_active_web_selection_instead_of_stale_dotenv`, `test_disabled_or_corrupt_configuration_does_not_fall_back` (2), `test_zero_or_embedding_only_models_are_connected_but_not_answerable` (2), `test_missing_docker_is_incomplete_and_does_not_guess_another_server`, `test_native_probe_reads_metadata_without_model_loading`, `test_environment_key_is_only_forwarded_to_its_original_endpoint` (2), `test_container_probe_stops_before_http_in_prod`, `test_container_probe_executes_in_existing_stable_project`, `test_malformed_config_response_is_reported_without_traceback`) | the doctor's legacy-metadata fallback removed (ops-c05) | the four `test_shared_*` tests (rewritten to call `diagnose(web_url, ...)`) plus the URL and transport tests keep the live diagnostics route path |
| `web/app/reset-local/page.test.tsx` (2 tests) | page removed (web-c01) | none needed |
| `web/lib/reset-browser.test.ts` (2 tests) | helper removed (web-c01) | none needed |
| `web/lib/browser-storage-persistence.test.ts :: never deletes the legacy conversation record when its replacement cannot persist` | `conversations:v1` fallback removed (web-c02) | `keeps a retired conversation record in recovery with one version warning instead of migrating it` (added) |
| `web/lib/browser-storage-persistence.test.ts :: migrates valid legacy conversations, theme and locale once` | renamed | `migrates unversioned theme and locale preferences once` |
| `web/components/local-connection-settings.test.tsx :: loads a legacy saved custom connection without switching it to Default` | 'Saved connection' fallback removed (web-c03) | none needed |
| `web/components/service-shell.test.tsx :: reads an interruption notice stored by an earlier version in the current language (%s)` | Korean case removed (web-c06) | `reads a stored interruption notice in the current language` |
| `web/lib/storage.test.ts :: drops retired snapshot and chat-preset fields from saved evaluation defaults` | write-back removed (web-c07); renamed | `ignores retired snapshot and chat-preset fields in saved evaluation defaults` |
| `web/components/documentation-navigation.test.tsx :: redirects an old Quick Start bookmark %s without changing its checkpoint` | legacy anchor redirects removed (web-c09) | none needed |
| `web/components/documentation-navigation.test.tsx :: redirects an old localized walkthrough anchor to its new section` | same | none needed |
| `web/components/documentation-navigation.test.tsx :: preserves an old root fragment when resolving the saved language` | same | none needed |
| `web/lib/documentation-registry.test.ts :: maps old walkthrough links to focused bilingual sections` | renamed | `resolves only registered Markdown files` |
| `web/lib/documentation-registry.test.ts :: preserves old Quick Start setup and procedure bookmarks (%s)` | renamed | `keeps Quick Start anchors on their own documents (%s)` |
| `web/components/tutorial-markdown.test.tsx :: uses explicit bilingual heading targets and maps legacy walkthrough links` | renamed | `uses explicit bilingual heading targets and resolves registered document links` |
| `web/lib/pipeline.test.ts :: preserves the intentional portfolio fixture when the public connection is confirmed` | portfolio fixture removed (web-c11) | none needed |
| `web/components/review-progress.test.tsx` (two 'Skipped: conversation reply without retrieval' assertions) | `casual_chat` rendering removed (web-c08); the tests themselves stay | same tests |
| `web/components/review-stage-details.test.tsx` (historical conversation-route notice assertion) | same | same test |

## Test files deleted on the branch

`git diff --diff-filter=D --name-only main..HEAD -- tests web`:

- `tests/evals/test_04_committed_candidate_intake.py`
- `tests/evals/test_curation.py`
- `tests/ingestion/chunk/golden.py` (test-support constants, not a test module)
- `tests/observability/test_cost.py`
- `tests/workflow/test_runner.py`
- `web/app/reset-local/page.test.tsx`
- `web/lib/reset-browser.test.ts`

(`web/app/reset-local/page.tsx` and `web/lib/reset-browser.ts` are the deleted page and helper
those web tests covered. `web/lib/canned.ts` was renamed to `web/lib/canned-test-support.ts`.)

## Tests added on the branch

Python (`git diff main..HEAD -- tests`, `+def test_` lines that are not renames of a removed test):

- `tests/api/test_review_profile.py`: `test_default_settings_keep_the_shipped_builtin_values`,
  `test_builtin_presets_inherit_configured_settings`, `test_deliberately_tuned_builtin_value_is_kept`,
  `test_stated_custom_values_win_and_omitted_values_inherit`,
  `test_administrator_profiles_follow_the_same_precedence` (BM25 precedence, D-4).
- `tests/api/test_runtime.py::test_served_retrieval_applies_bm25_precedence`,
  `tests/api/test_preset_store.py::test_catalog_and_resolution_present_the_effective_bm25_values`,
  `tests/api/test_admin_runtime.py::test_previews_run_and_present_the_effective_bm25_values`,
  `tests/evals/test_admin.py::test_queued_profiles_fill_unstated_bm25_values_from_settings`,
  `tests/release/test_02_release_app.py::test_runtime_composition_serves_the_configured_bm25_settings`.
- `tests/api/test_07_local_connection.py::test_retired_top_level_review_limits_are_rejected_as_unknown_fields`.
- `tests/db/test_startup.py::test_prepare_uses_the_shared_bootstrap_and_releases_its_engine`.
- `tests/llm/test_schemas.py::test_token_pricing_charges_cached_and_cache_write_input_at_policy_prices`.
- `tests/test_corpus_admin.py::test_historical_ingestion_without_selection_is_refused_on_retry`.
- `tests/scripts/stack/test_fresh.py::test_environment_reset_preserves_staged_changes`.

Web: `keeps a retired conversation record in recovery with one version warning instead of
migrating it` (`web/lib/browser-storage-persistence.test.ts`).

New test-support modules: `tests/llm/support.py` (`DeterministicLLMProvider`, `ChatReply`,
`TickClock`, `raw`), `tests/observability/support.py::persist_run_report`,
`tests/workflow/support.py::retrieval_result`, `web/lib/canned-test-support.ts`.

## Round 3: test pruning with per-test coverage evidence

Restored after the independent review, because the behaviour they assert had no other offline test: `tests/retrieval/test_translate.py::test_translate_query_fails_closed_instead_of_returning_the_original` (the translator's own refusal / schema-rejection gate), `tests/retrieval/test_lexical.py::test_search_executes_once_and_validates_database_mappings` (the only offline execution of `lexical_search`) and `tests/scripts/stack/test_quickstart.py::test_schema_drift_blocks_application_start` (a declined retry after schema drift never starts services). The review also restored the deterministic rows of `tests/api/test_runtime.py::test_supported_questions_reach_search` (zero model calls for rule-resolved questions), the `first_call=False` case of `tests/release/test_ai_allowance.py::test_streamed_actual_call_denial_keeps_error_and_done` (a second reservation denied mid-stream), `tests/release/test_compose_layers.py::test_overlays_declare_no_required_variables`, and added `tests/release/test_config.py::test_canned_mode_keeps_the_provider_off_even_with_a_key` and a `can_retry` assertion for historical ingest rows. The per-lane table below shows the counts before those changes.

Per-test branch coverage over `app/` and `scripts/` was recorded with `pytest --cov-context=test` (C tracer). Each lane agent read the evidence and every test in its directory; a test was removed only when a named kept test asserts the same behaviour (subsumed / duplicate), when two near-duplicates became one parametrized test with the same assertions (merged), when it exercised only a private helper already covered through its public caller, or when it pinned wording alone.

| lane | before | after | subsumed | duplicate | merged | private-helper | wording |
|---|---|---|---|---|---|---|---|
| agent | 60 | 48 | 3 | 0 | 9 | 0 | 0 |
| api | 301 | 247 | 25 | 29 | 0 | 0 | 0 |
| db | 25 | 22 | 0 | 1 | 2 | 0 | 0 |
| evals | 381 | 311 | 27 | 23 | 2 | 1 | 0 |
| ingestion | 568 | 527 | 25 | 5 | 1 | 0 | 0 |
| llm | 155 | 126 | 10 | 8 | 11 | 3 | 0 |
| observability | 45 | 42 | 1 | 0 | 2 | 0 | 0 |
| operator | 67 | 66 | 0 | 1 | 0 | 0 | 0 |
| release | 110 | 87 | 4 | 9 | 8 | 3 | 0 |
| retrieval | 281 | 215 | 24 | 31 | 4 | 6 | 1 |
| root | 78 | 73 | 3 | 1 | 0 | 1 | 0 |
| scripts | 375 | 340 | 11 | 11 | 6 | 0 | 0 |
| workflow | 100 | 76 | 2 | 8 | 16 | 0 | 0 |
| **total** | **2546** | **2180** | | | | | |

| removed or merged test | category | kept test(s) covering the same behaviour |
|---|---|---|
| `tests/agent/test_builtin_tools.py::test_compare_years_shares_one_query_embedding_cache` | merged | `tests/agent/test_builtin_tools.py::test_compare_years_groups_hits_per_sorted_year` |
| `tests/agent/test_decompose.py::test_decompose_query_returns_sub_questions_and_names_the_fallback_cause` | merged | `tests/agent/test_decompose.py::test_decomposed_retriever_gathers_per_sub_question_sessions_and_fuses`<br>`tests/agent/test_decompose.py::test_decomposed_retriever_logs_a_degraded_decomposition` |
| `tests/agent/test_loop.py::test_final_answer_requires_the_complete_retrieved_identity` | subsumed | `tests/agent/test_loop.py::test_conflicting_chunk_identity_is_rejected_and_kept_out_of_evidence` |
| `tests/agent/test_loop.py::test_not_in_docs_requires_no_evidence` | merged | `tests/agent/test_loop.py::test_final_answer_rejection_names_the_broken_field` |
| `tests/agent/test_loop.py::test_provider_failure_returns_a_typed_result` | merged | `tests/agent/test_loop.py::test_provider_failure_does_not_expose_exception_secrets`<br>`tests/agent/test_loop.py::test_tool_failures_become_explicit_observations` |
| `tests/agent/test_loop.py::test_token_budget_stops_before_another_provider_call` | merged | `tests/agent/test_loop.py::test_final_turn_cannot_succeed_after_token_budget_overshoot` |
| `tests/agent/test_loop.py::test_tool_error_detail_reaches_the_model` | subsumed | `tests/agent/test_mcp_server.py::test_mcp_call_tool_reports_errors_the_way_the_loop_does`<br>`tests/agent/test_loop.py::test_tool_failures_become_explicit_observations` |
| `tests/agent/test_loop.py::test_uncited_final_answer_is_rejected_then_corrected` | subsumed | `tests/agent/test_loop.py::test_tool_failures_become_explicit_observations`<br>`tests/agent/test_loop.py::test_conflicting_chunk_identity_is_rejected_and_kept_out_of_evidence` |
| `tests/agent/test_main.py::test_cli_rejects_out_of_range_limits_at_parse_time[argv0]` | merged | `tests/agent/test_main.py::test_cli_rejects_out_of_range_limits_at_parse_time[k]` |
| `tests/agent/test_main.py::test_cli_rejects_out_of_range_limits_at_parse_time[argv2]` | merged | `tests/agent/test_main.py::test_cli_rejects_out_of_range_limits_at_parse_time[max_iterations]` |
| `tests/agent/test_provider.py::test_openai_adapter_disables_hidden_sdk_retries_and_records_the_client_url` | merged | `tests/agent/test_provider.py::test_openai_adapter_closes_only_the_client_it_owns` |
| `tests/agent/test_registry.py::test_manual_names_every_tool_and_argument` | merged | `tests/agent/test_registry.py::test_specs_and_manual_publish_the_registered_tool` |
| `tests/api/test_05_runtime_topology.py::test_public_runtime_rejects_custom_prompt_policy_before_provider_or_database` | subsumed | `tests/api/test_runtime.py::test_production_rejects_local_and_custom_controls_before_retrieval`<br>`tests/api/test_07_local_connection.py::test_nonlive_public_retrieval_cannot_bypass_custom_policy_guard` |
| `tests/api/test_05_runtime_topology.py::test_runtime_openapi_includes_all_m5_resources` | subsumed | `tests/api/test_03_route_surface.py::test_openapi_exposes_resource_oriented_surface` |
| `tests/api/test_06_review_lifecycle.py::test_korean_preset_retrieval_uses_the_issuer_language_without_translation[sec-languages1]` | duplicate | `tests/api/test_06_review_lifecycle.py::test_korean_preset_retrieval_uses_the_issuer_language_without_translation[sec-languages2]`<br>`tests/api/test_06_review_lifecycle.py::test_korean_preset_retrieval_uses_the_issuer_language_without_translation[auto-languages0]` |
| `tests/api/test_07_local_connection.py::test_actual_loopback_same_origin_does_not_need_configured_proxy_origin[http://localhost:8000]` | duplicate | `tests/api/test_07_local_connection.py::test_actual_loopback_same_origin_does_not_need_configured_proxy_origin[https://127.0.0.1:8443]` |
| `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[http://localhost:9001-diagnostics]` | duplicate | `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[http://localhost:9001-disconnect]`<br>`tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[null-diagnostics]` |
| `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[http://localhost:9001-select]` | duplicate | `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[http://localhost:9001-disconnect]`<br>`tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[null-select]` |
| `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[http://localhost:9001-servers]` | duplicate | `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[http://localhost:9001-disconnect]`<br>`tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[null-servers]` |
| `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[https://unrelated.example-diagnostics]` | duplicate | `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[https://unrelated.example-disconnect]`<br>`tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[null-diagnostics]` |
| `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[https://unrelated.example-select]` | duplicate | `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[https://unrelated.example-disconnect]`<br>`tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[null-select]` |
| `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[https://unrelated.example-servers]` | duplicate | `tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[https://unrelated.example-disconnect]`<br>`tests/api/test_07_local_connection.py::test_browser_origin_blocks_every_local_connection_mutation[null-servers]` |
| `tests/api/test_07_local_connection.py::test_configured_loopback_aliases_work_through_next_rewrite[http://127.0.0.1:9000]` | duplicate | `tests/api/test_07_local_connection.py::test_configured_loopback_aliases_work_through_next_rewrite[http://localhost:9000]` |
| `tests/api/test_07_local_connection.py::test_retired_top_level_review_limits_are_rejected_as_unknown_fields[budget-value1]` | subsumed | `tests/api/test_schemas.py::test_removed_top_level_controls_are_rejected[budget-value2-ReviewRequest]`<br>`tests/api/test_errors.py::test_malformed_json_returns_typed_422_without_a_traceback` |
| `tests/api/test_07_local_connection.py::test_retired_top_level_review_limits_are_rejected_as_unknown_fields[max_context_chars-15000]` | subsumed | `tests/api/test_schemas.py::test_removed_top_level_controls_are_rejected[max_context_chars-10000-ReviewRequest]`<br>`tests/api/test_errors.py::test_malformed_json_returns_typed_422_without_a_traceback` |
| `tests/api/test_admin_routes.py::test_admin_routes_are_absent_without_explicit_composition` | subsumed | `tests/api/test_03_route_surface.py::test_openapi_exposes_resource_oriented_surface`<br>`tests/api/test_admin_routes.py::test_source_deletion_preview_is_admin_only_and_validates_exact_ids`<br>`tests/api/test_preset_store.py::test_admin_api_validation_and_production_boundary` |
| `tests/api/test_errors.py::test_empty_query_returns_typed_422` | subsumed | `tests/api/test_schemas.py::test_retrieve_request_is_strict_and_rejects_blank_or_unknown_input`<br>`tests/api/test_errors.py::test_malformed_json_returns_typed_422_without_a_traceback`<br>`tests/api/test_04_review_stream.py::test_stream_rejects_malformed_requests_before_streaming` |
| `tests/api/test_errors.py::test_expected_domain_problem_returns_typed_400` | subsumed | `tests/api/test_public_snapshot_details.py::test_missing_snapshot_safe_envelope`<br>`tests/api/test_admin_routes.py::test_history_routes_validate_scope_and_translate_conflicts` |
| `tests/api/test_execution.py::test_local_execution_publishes_measured_cpu_speed_to_readiness[v1-None-None]` | duplicate | `tests/api/test_execution.py::test_local_execution_publishes_measured_cpu_speed_to_readiness[v2-v1-None]`<br>`tests/llm/test_local_inventory.py::test_cpu_measurement_requires_a_known_matching_run_digest[]` |
| `tests/api/test_execution.py::test_local_execution_publishes_measured_cpu_speed_to_readiness[v2-v2-None]` | duplicate | `tests/api/test_execution.py::test_local_execution_publishes_measured_cpu_speed_to_readiness[v2-v1-None]`<br>`tests/api/test_execution.py::test_local_execution_publishes_measured_cpu_speed_to_readiness[v1-v1-10]`<br>`tests/llm/test_local_inventory.py::test_cpu_measurement_requires_a_known_matching_run_digest[d2]` |
| `tests/api/test_public_portfolio.py::test_unknown_preparation_is_not_zero[incompatible-True]` | duplicate | `tests/api/test_public_portfolio.py::test_unknown_preparation_is_not_zero[unavailable-True]` |
| `tests/api/test_review_profile.py::test_builtin_presets_inherit_configured_settings[accuracy]` | subsumed | `tests/api/test_preset_store.py::test_catalog_and_resolution_present_the_effective_bm25_values`<br>`tests/api/test_runtime.py::test_served_retrieval_applies_bm25_precedence[server1-None-expected1]` |
| `tests/api/test_review_profile.py::test_builtin_presets_inherit_configured_settings[balanced]` | subsumed | `tests/api/test_preset_store.py::test_catalog_and_resolution_present_the_effective_bm25_values`<br>`tests/api/test_runtime.py::test_served_retrieval_applies_bm25_precedence[server1-None-expected1]` |
| `tests/api/test_review_profile.py::test_builtin_presets_inherit_configured_settings[korean]` | subsumed | `tests/api/test_runtime.py::test_served_retrieval_applies_bm25_precedence[server1-None-expected1]` |
| `tests/api/test_review_profile.py::test_default_settings_keep_the_shipped_builtin_values[accuracy]` | subsumed | `tests/api/test_preset_store.py::test_server_resolves_canonical_files`<br>`tests/api/test_runtime.py::test_served_retrieval_applies_bm25_precedence[server0-None-expected0]` |
| `tests/api/test_review_profile.py::test_default_settings_keep_the_shipped_builtin_values[balanced]` | subsumed | `tests/api/test_preset_store.py::test_server_resolves_canonical_files`<br>`tests/api/test_runtime.py::test_served_retrieval_applies_bm25_precedence[server0-None-expected0]` |
| `tests/api/test_review_profile.py::test_default_settings_keep_the_shipped_builtin_values[korean]` | subsumed | `tests/api/test_preset_store.py::test_server_resolves_canonical_files`<br>`tests/api/test_runtime.py::test_served_retrieval_applies_bm25_precedence[server0-None-expected0]` |
| `tests/api/test_review_profile.py::test_deliberately_tuned_builtin_value_is_kept` | subsumed | `tests/api/test_preset_store.py::test_catalog_and_resolution_present_the_effective_bm25_values` |
| `tests/api/test_runtime.py::test_corpus_wide_scope_preserves_explicit_language_filter[en]` | duplicate | `tests/api/test_runtime.py::test_corpus_wide_scope_preserves_explicit_language_filter` |
| `tests/api/test_runtime.py::test_explicit_corpus_wide_scope_keeps_every_language[Compare all available companies' revenue-review]` | duplicate | `tests/api/test_runtime.py::test_explicit_corpus_wide_scope_keeps_every_language[retrieve-Compare all available companies' revenue]`<br>`tests/api/test_runtime.py::test_explicit_corpus_wide_scope_keeps_every_language[review-모든 회사의 매출을 비교해줘]` |
| `tests/api/test_runtime.py::test_followups_reach_retrieval_with_replaced_scope[그럼 2024년 매출은?-NVDA-2024]` | duplicate | `tests/api/test_runtime.py::test_followups_reach_retrieval_with_replaced_scope[그럼 2024년은?-NVDA-2024]` |
| `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[Nvidia revenue-NVDA-retrieve]` | duplicate | `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[What drove NVIDIA data center revenue growth?-NVDA-retrieve]` |
| `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[Nvidia revenue-NVDA-review]` | duplicate | `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[What drove NVIDIA data center revenue growth?-NVDA-review]` |
| `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[삼성전자 매출-005930-retrieve]` | duplicate | `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[삼성전자 메모리 사업의 주요 위험은 무엇인가요?-005930-retrieve]` |
| `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[삼성전자 매출-005930-review]` | duplicate | `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[삼성전자 메모리 사업의 주요 위험은 무엇인가요?-005930-review]` |
| `tests/api/test_runtime.py::test_korean_restatement_keeps_prior_filing_scope` | duplicate | `tests/api/test_runtime.py::test_followups_reach_retrieval_with_replaced_scope[방금 이야기해준거 한글로 다시 설명해줄래-NVDA-2023]` |
| `tests/api/test_runtime.py::test_review_preserves_original_question_across_search_rewriting[False]` | duplicate | `tests/api/test_runtime.py::test_review_preserves_original_question_across_search_rewriting[True]` |
| `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[Compare Nvidia and SanDisk-document_review-names2-explicit-unknown_issuer-gate-1-retrieve]` | duplicate | `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[retrieve-Nvidia and UnknownCorp revenue-document_review-names2-explicit-unknown_issuer-gate-1]` |
| `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[Compare Nvidia and SanDisk-document_review-names2-explicit-unknown_issuer-gate-1-review]` | duplicate | `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[review-Nvidia and UnknownCorp revenue-document_review-names3-explicit-unknown_issuer-gate-1]` |
| `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[Nvidia and NvidiaAI revenue-document_review-names4-explicit-unknown_issuer-gate-1-review]` | duplicate | `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[retrieve-Nvidia and NvidiaAI revenue-document_review-names3-explicit-unknown_issuer-gate-1]`<br>`tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[review-Nvidia and UnknownCorp revenue-document_review-names3-explicit-unknown_issuer-gate-1]` |
| `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[Nvidia or another company?-document_review-names7-unclear-ambiguous_issuer-gate-1-review]` | duplicate | `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[retrieve-Nvidia or another company?-document_review-names7-unclear-ambiguous_issuer-gate-1]`<br>`tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[review-그 회사의 성장 요인은?-document_review-names6-unclear-ambiguous_issuer-gate-1]`<br>`tests/api/test_runtime.py::test_classifier_all_without_corpus_wide_cue_is_clarified[review]` |
| `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[Pretend you are a cat-None-names9-None-unsupported_request-path-0-review]` | duplicate | `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[retrieve-Pretend you are a cat-None-names12-None-unsupported_request-path-0]`<br>`tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[review-고양이와 대화하기-None-names11-None-unsupported_request-path-0]` |
| `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[SanDisk growth drivers-document_review-names1-explicit-unknown_issuer-gate-1-review]` | duplicate | `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[retrieve-SanDisk growth drivers-document_review-names1-explicit-unknown_issuer-gate-1]`<br>`tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[review-Nvidia and UnknownCorp revenue-document_review-names3-explicit-unknown_issuer-gate-1]`<br>`tests/api/test_runtime.py::test_classifier_all_without_corpus_wide_cue_is_clarified[review]` |
| `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[샌디스크 성장 요인-document_review-names0-explicit-unknown_issuer-gate-1-review]` | duplicate | `tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[retrieve-샌디스크 성장 요인-document_review-names0-explicit-unknown_issuer-gate-1]`<br>`tests/api/test_runtime.py::test_routing_stops_before_search_and_answer[review-Nvidia and UnknownCorp revenue-document_review-names3-explicit-unknown_issuer-gate-1]` |
| `tests/api/test_runtime.py::test_server_enforces_history_bounds[0-0]` | subsumed | `tests/api/test_runtime.py::test_zero_history_bound_prevents_implicit_inheritance` |
| `tests/api/test_runtime.py::test_server_enforces_history_bounds[2-2]` | subsumed | `tests/api/test_runtime.py::test_followups_reach_retrieval_with_replaced_scope[그럼 2024년은?-NVDA-2024]` |
| `tests/api/test_runtime.py::test_supported_questions_reach_search[Compare all available companies' revenue-None-None-None-0]` | subsumed | `tests/api/test_runtime.py::test_explicit_corpus_wide_scope_keeps_every_language[retrieve-Compare all available companies' revenue]` |
| `tests/api/test_runtime.py::test_supported_questions_reach_search[Compare all available companies-None-None-None-0]` | subsumed | `tests/api/test_runtime.py::test_explicit_corpus_wide_scope_keeps_every_language[retrieve-Compare all available companies' revenue]` |
| `tests/api/test_runtime.py::test_supported_questions_reach_search[Nvidia growth drivers-None-None-None-0]` | subsumed | `tests/api/test_runtime.py::test_known_company_questions_reach_retrieval_without_classifier[What drove NVIDIA data center revenue growth?-NVDA-retrieve]` |
| `tests/api/test_runtime.py::test_supported_questions_reach_search[그럼 2024년은?-None-None-NVDA revenue 2023-0]` | subsumed | `tests/api/test_runtime.py::test_followups_reach_retrieval_with_replaced_scope[그럼 2024년은?-NVDA-2024]` |
| `tests/api/test_runtime_gate.py::test_gate_counts_background_cleanup_after_response_body` | subsumed | `tests/api/test_runtime_gate.py::test_stream_remains_active_until_cancelled_producer_cleanup_finishes[disconnect]`<br>`tests/api/test_runtime_gate.py::test_stream_remains_active_until_cancelled_producer_cleanup_finishes[send]` |
| `tests/api/test_schemas.py::test_budget_run_maps_to_discriminated_failure` | subsumed | `tests/api/test_02_ingest_review.py::test_review_budget_exhaustion_is_a_structured_429` |
| `tests/api/test_schemas.py::test_evidence_projection_exposes_complete_source_identity` | subsumed | `tests/api/test_01_resource_reads.py::test_retrieve_route_returns_complete_evidence_identity` |
| `tests/api/test_schemas.py::test_run_response_redacts_public_prompt_and_failure_text` | subsumed | `tests/api/test_04_review_stream.py::test_stream_preserves_typed_service_errors_and_redacts_terminal_reports` |
| `tests/api/test_schemas.py::test_successful_run_maps_to_strict_workflow_report` | subsumed | `tests/api/test_02_ingest_review.py::test_review_route_returns_supported_evidence_synchronously`<br>`tests/api/test_schemas.py::test_run_response_rejects_mismatched_success_and_failure_shapes`<br>`tests/api/test_04_review_stream.py::test_stream_emits_node_events_then_the_terminal_run` |
| `tests/api/test_scope_diagnostics.py::test_actual_manifest_failure_causes_and_recovery[missing_file]` | duplicate | `tests/api/test_scope_diagnostics.py::test_actual_manifest_failure_causes_and_recovery[permission]`<br>`tests/api/test_scope_diagnostics.py::test_unavailable_job_history_preserves_the_original_manifest_error`<br>`tests/api/test_scope_diagnostics.py::test_http_and_stream_keep_the_same_typed_scope_failure[True]` |
| `tests/db/test_bootstrap.py::test_vector_extension_is_created_idempotently` | merged | `tests/db/test_bootstrap.py::test_bootstrap_enables_vector_and_checks_drift_before_creating_tables` |
| `tests/db/test_models.py::test_index_sql_constants_agree_with_the_lexical_plans` | merged | `tests/db/test_models.py::test_search_vector_is_computed_per_corpus_language` |
| `tests/db/test_startup.py::test_runtime_prepares_before_exec[False]` | duplicate | `tests/db/test_startup.py::test_runtime_prepares_before_exec` |
| `tests/evals/test_03_budget_gated_run.py::test_an_exceeded_indexing_budget_fails_the_run` | subsumed | `tests/evals/test_03_budget_gated_run.py::test_the_command_exit_status_follows_the_measured_verdict`<br>`tests/evals/test_measurement.py::test_budgets_pass_only_when_every_measured_limit_holds` |
| `tests/evals/test_03_budget_gated_run.py::test_the_budget_arm_is_the_same_however_the_strategy_axis_is_ordered` | subsumed | `tests/evals/test_run.py::test_the_budget_arm_ignores_the_order_the_axes_were_typed`<br>`tests/evals/test_run.py::test_repeated_or_reordered_axes_normalize_to_the_canonical_matrix`<br>`tests/evals/test_run.py::test_the_budget_arm_names_a_ranker_only_when_it_runs_a_lexical_query[strategies0-rankers0-expected0]` |
| `tests/evals/test_03_budget_gated_run.py::test_the_budget_artifact_names_the_arm_its_latency_belongs_to` | merged | `tests/evals/test_03_budget_gated_run.py::test_a_full_run_writes_one_artifact_per_arm_and_a_budget_artifact_naming_its_arm` |
| `tests/evals/test_ablation.py::test_bm25_arms_record_explicit_project_defaults_only_when_used` | merged | `tests/evals/test_ablation.py::test_config_provenance_records_the_ranker_and_bm25_defaults_only_where_used` |
| `tests/evals/test_ablation.py::test_bm25_config_rejects_missing_or_invalid_parameters[changes1..changes7] (k1 0, k1 inf, b None, b -0.1, b nan, idf None, idf unknown)` | subsumed | `tests/evals/test_arms.py::test_a_bm25_arm_is_rejected_before_it_can_be_bound[values0..values5]`<br>`tests/evals/test_ablation.py::test_bm25_config_rejects_missing_parameters` |
| `tests/evals/test_ablation.py::test_experiment_matrix_names_are_unique_and_filename_safe` | subsumed | `tests/evals/test_03_budget_gated_run.py::test_a_full_run_writes_one_artifact_per_arm_and_a_budget_artifact_naming_its_arm`<br>`tests/evals/test_ablation.py::test_experiment_config_rejects_ambiguous_or_inconsistent_values[changes0]`<br>`tests/evals/test_ablation.py::test_config_provenance_records_the_ranker_and_bm25_defaults_only_where_used` |
| `tests/evals/test_ablation.py::test_matrix_is_sorted_the_same_way_however_the_axes_are_given` | subsumed | `tests/evals/test_ablation.py::test_experiment_matrix_crosses_chunking_retrieval_and_lexical_ranker` |
| `tests/evals/test_ablation.py::test_non_bm25_config_rejects_bm25_parameters[None]` | duplicate | `tests/evals/test_ablation.py::test_non_bm25_config_rejects_bm25_parameters`<br>`tests/evals/test_arms.py::test_bm25_values_are_rejected_on_an_arm_that_runs_no_bm25_query` |
| `tests/evals/test_ablation.py::test_vector_arm_is_not_duplicated_across_rankers` | subsumed | `tests/evals/test_ablation.py::test_experiment_matrix_crosses_chunking_retrieval_and_lexical_ranker`<br>`tests/evals/test_03_budget_gated_run.py::test_a_narrowed_matrix_runs_exactly_the_requested_arms[argv1-2]` |
| `tests/evals/test_admin.py::test_quick_evaluation_preparation_matches_the_selected_strategy[hybrid-True-True-True]` | subsumed | `tests/evals/test_preparation.py::test_preparation_distinguishes_index_and_exact_source_versions[ready-ready]` |
| `tests/evals/test_arms.py::test_a_bm25_arm_is_rejected_before_it_can_be_bound[values2] (k1 inf) and [values7] (idf None)` | duplicate | `tests/evals/test_arms.py::test_a_bm25_arm_is_rejected_before_it_can_be_bound[values1]`<br>`tests/evals/test_arms.py::test_a_bm25_arm_is_rejected_before_it_can_be_bound[values0]`<br>`tests/evals/test_arms.py::test_a_bm25_arm_is_rejected_before_it_can_be_bound[values5]` |
| `tests/evals/test_arms.py::test_a_mislabeled_arm_is_rejected_at_bind_time[kwargs2-requires an explicit lexical ranker] (lexical, no ranker)` | duplicate | `tests/evals/test_arms.py::test_a_mislabeled_arm_is_rejected_at_bind_time[kwargs1-requires an explicit lexical ranker]`<br>`tests/evals/test_arms.py::test_a_mislabeled_arm_is_rejected_at_bind_time[kwargs3-requires an explicit lexical ranker]` |
| `tests/evals/test_arms.py::test_bm25_values_are_rejected_on_an_arm_that_runs_no_bm25_query[None]` | duplicate | `tests/evals/test_arms.py::test_bm25_values_are_rejected_on_an_arm_that_runs_no_bm25_query` |
| `tests/evals/test_arms.py::test_resolve_bm25_parameters_returns_values_only_for_a_bm25_arm` | private-helper | `tests/evals/test_arms.py::test_bm25_parameters_are_identical_in_lexical_and_hybrid_paths`<br>`tests/evals/test_arms.py::test_a_non_bm25_hybrid_arm_forwards_no_bm25_values`<br>`tests/evals/test_ablation.py::test_config_provenance_records_the_ranker_and_bm25_defaults_only_where_used` |
| `tests/evals/test_bilingual.py::test_the_korean_suite_ships_beside_the_frozen_english_one` | subsumed | `tests/evals/test_bilingual.py::test_load_bilingual_suites_binds_both_languages_to_the_same_spans` |
| `tests/evals/test_bilingual.py::test_validate_twin_cases_accepts_the_shipped_suites` | subsumed | `tests/evals/test_bilingual.py::test_load_bilingual_suites_binds_both_languages_to_the_same_spans` |
| `tests/evals/test_bilingual.py::test_validate_twin_cases_rejects_suites_that_could_move_a_metric[category, facet, tags, reference_answer]` | duplicate | `tests/evals/test_bilingual.py::test_validate_twin_cases_rejects_suites_that_could_move_a_metric[en_changes1-ko_changes1-answers]`<br>`tests/evals/test_bilingual.py::test_the_twin_invariant_set_covers_every_field_a_suite_could_drift_on` |
| `tests/evals/test_cli.py::test_positive_int_accepts_a_positive_count[1-1], [20-20]` | subsumed | `tests/evals/test_03_budget_gated_run.py::test_a_shortened_budget_run_is_not_assessed_against_the_full_query_limit`<br>`tests/evals/test_run.py::test_a_candidate_depth_below_k_is_rejected_by_the_parser` |
| `tests/evals/test_cli.py::test_positive_int_rejects_a_nonpositive_count[-1]` | duplicate | `tests/evals/test_cli.py::test_positive_int_rejects_a_nonpositive_count` |
| `tests/evals/test_cli.py::test_unit_ratio_accepts_the_closed_upper_bound[1-1.0]` | subsumed | `tests/evals/test_crosslingual.py::test_the_command_rejects_an_impossible_parity_floor_before_measuring_anything`<br>`tests/evals/test_cli.py::test_unit_ratio_accepts_an_interior_ratio` |
| `tests/evals/test_cli.py::test_unit_ratio_rejects_a_ratio_outside_the_unit_interval[-0.5], [1.5], [inf]` | duplicate | `tests/evals/test_cli.py::test_unit_ratio_rejects_a_ratio_outside_the_unit_interval[0]`<br>`tests/evals/test_cli.py::test_unit_ratio_rejects_a_ratio_outside_the_unit_interval[nan]`<br>`tests/evals/test_crosslingual.py::test_the_command_rejects_an_impossible_parity_floor_before_measuring_anything` |
| `tests/evals/test_corpus.py::test_build_chunking_batch_reuses_supplied_filings_without_loading_manifest` | subsumed | `tests/evals/test_corpus.py::test_chunking_batch_passes_the_token_target_to_the_chunker`<br>`tests/evals/test_corpus.py::test_chunking_respects_the_selected_models_actual_token_limit` |
| `tests/evals/test_golden_admin.py::test_invalid_or_builtin_filenames_cannot_be_written[bad/path.json]` | duplicate | `tests/evals/test_golden_admin.py::test_invalid_or_builtin_filenames_cannot_be_written[../escape.json]`<br>`tests/evals/test_golden_admin.py::test_invalid_or_builtin_filenames_cannot_be_written[wrong.txt]` |
| `tests/evals/test_identity.py::test_artifact_filename_rejects_a_name_that_would_leave_the_artifact_directory[Not Kebab Case]` | duplicate | `tests/evals/test_identity.py::test_artifact_filename_rejects_a_name_that_would_leave_the_artifact_directory[../../escape]`<br>`tests/evals/test_identity.py::test_artifact_filename_rejects_a_name_that_would_leave_the_artifact_directory[]` |
| `tests/evals/test_identity.py::test_the_shared_vocabulary_covers_every_retrieval_path_and_ranker` | subsumed | `tests/evals/test_ablation.py::test_experiment_matrix_crosses_chunking_retrieval_and_lexical_ranker`<br>`tests/evals/test_run.py::test_cli_defaults_to_the_isolated_deterministic_ten_arm_matrix`<br>`tests/evals/test_ablation.py::test_config_provenance_records_the_ranker_and_bm25_defaults_only_where_used` |
| `tests/evals/test_loader.py::test_loader_accepts_a_case_bound_to_its_exact_source_snapshot` | subsumed | `tests/evals/test_loader.py::test_loader_distinguishes_acquired_bytes_from_decoded_source_digest`<br>`tests/evals/test_01_golden_corpus_binding.py::test_committed_suite_loads_with_exact_balance_and_pending_status` |
| `tests/evals/test_measurement.py::test_a_shortened_run_is_assessed_against_a_shortened_budget` | subsumed | `tests/evals/test_03_budget_gated_run.py::test_a_shortened_budget_run_is_not_assessed_against_the_full_query_limit`<br>`tests/evals/test_measurement.py::test_query_budget_fails_only_after_the_explicit_limit` |
| `tests/evals/test_measurement.py::test_a_vector_budget_arm_records_no_lexical_provenance` | subsumed | `tests/evals/test_03_budget_gated_run.py::test_a_full_run_writes_one_artifact_per_arm_and_a_budget_artifact_naming_its_arm`<br>`tests/evals/test_measurement.py::test_budget_artifact_records_the_arm_the_query_budget_ran_on` |
| `tests/evals/test_measurement.py::test_indexing_budget_keeps_configuration_and_provider_provenance` | subsumed | `tests/evals/test_measurement.py::test_indexing_payload_separates_shared_and_target_work`<br>`tests/evals/test_measurement.py::test_budgets_pass_only_when_every_measured_limit_holds` |
| `tests/evals/test_measurement.py::test_query_budget_rejects_a_hit_count_that_is_not_a_positive_integer[-1]` | duplicate | `tests/evals/test_measurement.py::test_query_budget_rejects_a_hit_count_that_is_not_a_positive_integer[0]`<br>`tests/evals/test_measurement.py::test_query_budget_rejects_a_hit_count_that_is_not_a_positive_integer[True]` |
| `tests/evals/test_measurement.py::test_query_budget_seconds_scale_with_the_requested_query_count` | subsumed | `tests/evals/test_03_budget_gated_run.py::test_a_shortened_budget_run_is_not_assessed_against_the_full_query_limit`<br>`tests/evals/test_measurement.py::test_200_query_budget_measures_exact_boundary_without_storing_fake_results` |
| `tests/evals/test_parity.py::test_assess_parity_fails_closed_when_the_english_slice_scored_zero` | subsumed | `tests/evals/test_parity.py::test_parity_markdown_renders_the_verdict_and_the_undefined_ratio`<br>`tests/evals/test_parity.py::test_native_zero_slice_fails_closed_for_either_direction` |
| `tests/evals/test_preparation.py::test_preparation_distinguishes_index_and_exact_source_versions[missing_vectors-index_update_required]` | subsumed | `tests/evals/test_preparation.py::test_preparation_distinguishes_index_and_exact_source_versions[missing_bm25-index_update_required]`<br>`tests/evals/test_admin.py::test_quick_evaluation_preparation_matches_the_selected_strategy[hybrid-False-True-False]`<br>`tests/evals/test_admin.py::test_waiting_evaluation_deduplicates_and_rechecks_preparation[False]` |
| `tests/evals/test_regression.py::test_config_serialization_rejects_ambiguous_or_non_json_values[config0-config keys must be strings]` | duplicate | `tests/evals/test_regression.py::test_config_serialization_rejects_ambiguous_or_non_json_values[config1-config keys must be strings]` |
| `tests/evals/test_regression.py::test_persisted_runs_must_carry_metrics_the_gate_can_read[run_metrics0-run metrics are missing recall_at_k]` | duplicate | `tests/evals/test_regression.py::test_persisted_runs_must_carry_metrics_the_gate_can_read[run_metrics1-run metrics are missing recall_at_k]` |
| `tests/evals/test_run.py::test_cli_can_narrow_the_ranker_axis` | subsumed | `tests/evals/test_run.py::test_duplicate_chunk_targets_and_rankers_normalize_the_same_way`<br>`tests/evals/test_03_budget_gated_run.py::test_a_narrowed_matrix_runs_exactly_the_requested_arms[argv2-2]` |
| `tests/evals/test_run.py::test_repeated_or_reordered_axes_normalize_to_the_canonical_matrix[argv0-expected0], [argv1-expected1]` | duplicate | `tests/evals/test_run.py::test_repeated_or_reordered_axes_normalize_to_the_canonical_matrix` |
| `tests/evals/test_run.py::test_the_budget_arm_ignores_the_order_the_axes_were_typed[strategies0], [strategies2]` | duplicate | `tests/evals/test_run.py::test_the_budget_arm_ignores_the_order_the_axes_were_typed` |
| `tests/evals/test_run.py::test_the_budget_arm_names_a_ranker_only_when_it_runs_a_lexical_query[strategies1-rankers1-expected1]` | duplicate | `tests/evals/test_run.py::test_the_budget_arm_names_a_ranker_only_when_it_runs_a_lexical_query[strategies0-rankers0-expected0]` |
| `tests/evals/test_scoring.py::test_a_chunk_far_wider_than_the_gold_span_is_still_relevant` | subsumed | `tests/evals/test_scoring.py::test_rechunked_and_reidentified_hits_preserve_scores`<br>`tests/evals/test_scoring.py::test_one_broad_chunk_can_cover_multiple_distinct_gold_spans` |
| `tests/evals/test_scoring.py::test_an_exactly_coincident_span_is_fully_covered` | subsumed | `tests/evals/test_scoring.py::test_partial_coverage_includes_the_threshold_and_rejects_the_step_below`<br>`tests/evals/test_scoring.py::test_suite_metrics_are_macro_averages_with_deterministic_case_order`<br>`tests/evals/test_scoring.py::test_multiple_gold_spans_are_counted_once_each` |
| `tests/evals/test_scoring.py::test_disjoint_touching_or_wrong_snapshot_spans_never_match[candidate1]` | duplicate | `tests/evals/test_scoring.py::test_disjoint_touching_or_wrong_snapshot_spans_never_match[candidate0]` |
| `tests/evals/test_scoring.py::test_duplicate_hits_do_not_double_count_one_gold_span` | subsumed | `tests/evals/test_scoring.py::test_multiple_gold_spans_are_counted_once_each` |
| `tests/evals/test_scoring.py::test_k_must_be_a_positive_integer[-1], ["1"]` | duplicate | `tests/evals/test_scoring.py::test_k_must_be_a_positive_integer[0]`<br>`tests/evals/test_scoring.py::test_k_must_be_a_positive_integer[True]`<br>`tests/evals/test_scoring.py::test_k_must_be_a_positive_integer[1.0]` |
| `tests/evals/test_scoring.py::test_no_hit_has_zero_metrics_and_no_rank` | subsumed | `tests/evals/test_scoring.py::test_empty_retrieval_list_is_a_no_hit`<br>`tests/evals/test_scoring.py::test_first_relevant_rank_is_limited_to_top_k`<br>`tests/evals/test_scoring.py::test_disjoint_touching_or_wrong_snapshot_spans_never_match[candidate0]` |
| `tests/evals/test_scoring.py::test_one_chunk_boundary_inside_a_gold_span_never_makes_it_unscoreable[199]` | duplicate | `tests/evals/test_scoring.py::test_one_chunk_boundary_inside_a_gold_span_never_makes_it_unscoreable[101]`<br>`tests/evals/test_scoring.py::test_one_chunk_boundary_inside_a_gold_span_never_makes_it_unscoreable[150]` |
| `tests/evals/test_snapshots.py::test_snapshot_requires_exact_evaluated_embedding_identity[payload1] ({})` | duplicate | `tests/evals/test_snapshots.py::test_snapshot_requires_exact_evaluated_embedding_identity[payload2]`<br>`tests/evals/test_snapshots.py::test_snapshot_requires_exact_evaluated_embedding_identity[None]` |
| `tests/evals/test_snapshots.py::test_snapshot_resource_carries_the_built_in_suite_title[dart-ko-DART retrieval · Korean]` | duplicate | `tests/evals/test_snapshots.py::test_snapshot_resource_carries_the_built_in_suite_title[sec-en-SEC retrieval]`<br>`tests/evals/test_admin.py::test_suite_catalog_preserves_unapproved_provenance` |
| `tests/evals/test_types.py::test_absent_case_has_no_source_span` | subsumed | `tests/evals/test_retrieval_eval.py::test_runner_records_all_cases_but_scores_only_source_bearing_positives`<br>`tests/evals/test_01_golden_corpus_binding.py::test_committed_suite_loads_with_exact_balance_and_pending_status` |
| `tests/evals/test_types.py::test_answer_span_rejects_invalid_hashes_offsets_and_coercion[start_char-10]` | duplicate | `tests/evals/test_types.py::test_answer_span_rejects_invalid_hashes_offsets_and_coercion[start_char-True]` |
| `tests/evals/test_types.py::test_case_id_accepts_any_suite_slug[m3c-01]` | subsumed | `tests/evals/test_types.py::test_public_golden_contract_is_strict_and_immutable`<br>`tests/evals/test_types.py::test_case_id_accepts_any_suite_slug[retrieval-ko-07]` |
| `tests/evals/test_types.py::test_case_id_rejects_non_slug_values[m3c_01], [m3c-01 ]` | duplicate | `tests/evals/test_types.py::test_case_id_rejects_non_slug_values[]`<br>`tests/evals/test_types.py::test_case_id_rejects_non_slug_values[M3C-01]`<br>`tests/evals/test_types.py::test_case_id_rejects_non_slug_values[-m3c-01]` |
| `tests/evals/test_types.py::test_unapproved_agent_provenance_is_required[overrides2] ({"human_verified": True})` | duplicate | `tests/evals/test_types.py::test_unapproved_agent_provenance_is_required[overrides3]` |
| `tests/ingestion/chunk/test_02_text.py::test_ordinals_are_dense_and_source_ordered` | subsumed | `tests/ingestion/seed/test_03_corpus.py::test_batch_preserves_every_selected_document_and_bounded_chunk`<br>`tests/ingestion/chunk/test_02_text.py::test_chunk_spans_overlap_only_when_sharing_enclosing_source` |
| `tests/ingestion/chunk/test_03_tables.py::test_small_table_stays_whole_with_row_level_provenance` | subsumed | `tests/ingestion/test_01_structural_budget.py::test_merged_cells_keep_source_relationships_and_numeric_rendering`<br>`tests/ingestion/test_01_structural_budget.py::test_unit_column_preserves_original_scale_header_and_cell_relationships`<br>`tests/ingestion/test_01_structural_budget.py::test_adjacent_date_unit_caption_records_its_own_span_without_changing_data_span` |
| `tests/ingestion/chunk/test_03_tables.py::test_table_chunk_identities_are_unique_within_a_document` | subsumed | `tests/ingestion/chunk/test_05_golden.py::test_corpus_chunk_identities_are_deterministic` |
| `tests/ingestion/edgar/test_02_segment.py::test_detect_number_learns_the_loosest_observed_heading_rule` | subsumed | `tests/ingestion/edgar/test_02_segment.py::test_build_profile_records_detected_rules_and_item_count` |
| `tests/ingestion/edgar/test_02_segment.py::test_detect_number_returns_empty_without_item_heading_candidates` | subsumed | `tests/ingestion/test_01_segmentation_routing.py::test_detect_segmentation_uses_number_then_xref_then_undefined` |
| `tests/ingestion/edgar/test_03_validate.py::test_classify_sections_recognizes_proxy_references` | duplicate | `tests/ingestion/edgar/test_02_segment.py::test_segment_classifies_empty_and_incorporated_sections` |
| `tests/ingestion/edgar/test_03_validate.py::test_validate_collects_multiple_problems_in_a_list` | subsumed | `tests/ingestion/edgar/test_03_validate.py::test_validate_catches_count_missing_items_duplicates_and_order` |
| `tests/ingestion/edgar/test_04_profile.py::test_missing_profile_returns_none` | subsumed | `tests/ingestion/edgar/test_04_profile.py::test_failed_bootstrap_profile_is_not_saved` |
| `tests/ingestion/edgar/test_04_profile.py::test_profile_save_load_roundtrip` | subsumed | `tests/ingestion/edgar/test_04_profile.py::test_each_profile_year_is_self_contained` |
| `tests/ingestion/seed/test_01_records.py::test_record_conversion_is_deterministic` | subsumed | `tests/ingestion/seed/test_01_records.py::test_parse_once_batch_exactly_matches_build_seed_batch` |
| `tests/ingestion/seed/test_02_upserts.py::test_chunk_upsert_leaves_independent_embedding_versions_untouched` | merged | `tests/ingestion/seed/test_02_upserts.py::test_chunk_upsert_targets_stable_identity_and_never_writes_embeddings` |
| `tests/ingestion/test_02_corpus_parsing.py::test_no_extra_sec_items[10 corpus documents]` | duplicate | `tests/ingestion/test_02_corpus_parsing.py::test_no_document_invents_an_item_outside_the_sec_vocabulary` |
| `tests/ingestion/test_dart.py::test_dart_section_title_returns_only_the_division_name` | subsumed | `tests/ingestion/test_registry.py::test_section_title_uses_only_the_named_registry`<br>`tests/ingestion/test_registry.py::test_registry_configuration_is_immutable_and_has_no_chunk_profiles` |
| `tests/ingestion/test_dart.py::test_parse_dart_filing_keeps_sec_vocabulary_out_of_sections` | subsumed | `tests/ingestion/test_dart.py::test_segment_builds_one_section_per_numbered_division`<br>`tests/ingestion/test_06_dart_parsing.py::test_dart_citations_use_the_registry_section_labels` |
| `tests/ingestion/test_dart.py::test_parse_dart_filing_rejects_a_source_that_drifted_from_the_manifest` | duplicate | `tests/ingestion/test_dart.py::test_parse_dart_filing_rejects_a_truncated_source`<br>`tests/ingestion/test_manifest.py::test_roundtrip_and_source_verification` |
| `tests/ingestion/test_dart_api.py::test_a_missing_manifest_is_a_first_run` | duplicate | `tests/ingestion/test_edgar_api.py::test_missing_canonical_manifest_starts_a_new_corpus` |
| `tests/ingestion/test_dart_api.py::test_a_second_fiscal_year_does_not_erase_the_first` | subsumed | `tests/ingestion/test_acquisition.py::test_mixed_catalog_retains_existing_selection_and_source_identities` |
| `tests/ingestion/test_dart_api.py::test_decode_source_honours_the_declared_encoding` | subsumed | `tests/ingestion/test_dart_api.py::test_archive_document_writes_utf8_and_records_matching_identity` |
| `tests/ingestion/test_dart_api.py::test_manifest_without_common_identity_is_rejected` | duplicate | `tests/ingestion/test_edgar_api.py::test_manifest_refuses_legacy_lists` |
| `tests/ingestion/test_dart_api.py::test_non_zip_body_reports_the_dart_status` | subsumed | `tests/ingestion/test_dart_api.py::test_fetch_document_archive_rejects_an_error_body` |
| `tests/ingestion/test_dart_api.py::test_parse_corp_codes_rejects_a_missing_stock_code` | subsumed | `tests/ingestion/test_dart_api.py::test_unknown_issuer_fetches_archive_and_requires_an_exact_resolution[False]` |
| `tests/ingestion/test_dart_api.py::test_select_primary_member_picks_the_report_by_exact_name` | subsumed | `tests/ingestion/test_dart_api.py::test_archive_document_writes_utf8_and_records_matching_identity` |
| `tests/ingestion/test_dart_api.py::test_two_receipts_for_one_issuer_year_remain_distinct` | subsumed | `tests/ingestion/test_dart_api.py::test_same_year_missing_receipt_is_reacquired_without_replacing_ready_filing` |
| `tests/ingestion/test_edgar_api.py::test_a_filing_already_in_the_manifest_is_not_added_twice` | subsumed | `tests/ingestion/test_edgar_api.py::test_year_scope_does_not_download_other_catalog_years` |
| `tests/ingestion/test_edgar_api.py::test_manifest_round_trips_through_the_writer` | subsumed | `tests/ingestion/test_manifest.py::test_roundtrip_and_source_verification`<br>`tests/ingestion/test_dart_api.py::test_manifest_round_trips_with_korean_names_intact` |
| `tests/ingestion/test_edgar_api.py::test_store_creates_the_issuer_directory_and_leaves_no_partial` | subsumed | `tests/ingestion/test_edgar_api.py::test_failed_write_leaves_no_partial_file`<br>`tests/ingestion/test_acquisition.py::test_public_source_bytes_remain_readable_across_runtime_users` |
| `tests/ingestion/test_edgar_api.py::test_submission_columns_join_by_position` | subsumed | `tests/ingestion/test_edgar_api.py::test_discovered_entry_uses_common_normalized_metadata`<br>`tests/ingestion/test_edgar_api.py::test_only_unamended_annual_reports_inside_the_range_are_selected` |
| `tests/ingestion/test_edgar_api.py::test_valid_manifest_is_returned_in_order` | subsumed | `tests/ingestion/test_edgar_api.py::test_year_scope_does_not_download_other_catalog_years` |
| `tests/ingestion/test_parser.py::test_leaf_blocks_never_loses_a_table[2 cases]` | subsumed | `tests/ingestion/test_parser.py::test_leaf_blocks_returns_expected_block_counts`<br>`tests/ingestion/test_parser.py::test_leaf_blocks_groups_a_legacy_table_as_one_block` |
| `tests/ingestion/test_tables.py::test_data_table_keeps_captions_inline` | subsumed | `tests/ingestion/test_tables.py::test_unit_caption_row_moves_ahead_of_the_table` |
| `tests/ingestion/test_tables.py::test_markdown_rows_have_the_same_width` | subsumed | `tests/ingestion/test_tables.py::test_multirow_header_is_merged_per_column`<br>`tests/ingestion/chunk/test_03_tables.py::test_table_row_width_is_stable` |
| `tests/llm/test_estimate.py::test_encoding_names_resolve_without_loading_tokenizer_data` | merged | `tests/llm/test_estimate.py::test_encoding_names_resolve_from_model_tables_without_loading_tokenizer_data` |
| `tests/llm/test_estimate.py::test_projection_is_skipped_and_not_retried_when_no_encoding_loads` | subsumed | `tests/llm/test_estimate.py::test_recognized_models_reach_the_same_guarded_loader_as_unknown_ones` |
| `tests/llm/test_estimate.py::test_unknown_models_fall_back_to_o200k_and_openai_models_use_their_encoding` | merged | `tests/llm/test_estimate.py::test_encoding_names_resolve_from_model_tables_without_loading_tokenizer_data` |
| `tests/llm/test_local.py::test_ollama_keeps_the_configured_window_when_the_remaining_budget_shrinks` | merged | `tests/llm/test_local.py::test_ollama_request_states_its_window_and_maps_the_native_reply[12600-12600]` |
| `tests/llm/test_local.py::test_ollama_native_normalizes_structured_output_and_usage` | merged | `tests/llm/test_local.py::test_ollama_request_states_its_window_and_maps_the_native_reply[None-150]` |
| `tests/llm/test_local.py::test_ollama_request_asks_for_a_window_that_fits_the_budget` | merged | `tests/llm/test_local.py::test_ollama_request_states_its_window_and_maps_the_native_reply[None-150]` |
| `tests/llm/test_local_connection.py::test_default_resolves_runtime_and_legacy_matching_choice_without_writes[http://127.0.0.1:11434]` | duplicate | `tests/llm/test_local_connection.py::test_default_resolves_runtime_and_legacy_matching_choice_without_writes` |
| `tests/llm/test_local_connection.py::test_explicit_schemes_and_ports_are_preserved[http://host-None]` | duplicate | `tests/llm/test_local_connection.py::test_explicit_schemes_and_ports_are_preserved[https://host-None]`<br>`tests/llm/test_local_connection.py::test_saved_connection_restart_disconnect_and_reset` |
| `tests/llm/test_local_connection.py::test_prepare_model_is_disabled_in_production` | merged | `tests/llm/test_local_connection.py::test_corrupt_file_fails_closed_and_prod_does_not_read_or_probe` |
| `tests/llm/test_local_connection.py::test_saved_choice_overrides_invalid_initial_url[disabled]` | subsumed | `tests/llm/test_local_connection.py::test_saved_choice_overrides_invalid_initial_url`<br>`tests/llm/test_local_connection.py::test_saved_connection_restart_disconnect_and_reset` |
| `tests/llm/test_local_connection.py::test_saved_connection_is_readable_by_the_configured_host_group` | merged | `tests/llm/test_local_connection.py::test_saved_connection_restart_disconnect_and_reset` |
| `tests/llm/test_local_diagnostics.py::test_transport_failure_guidance_never_contains_the_raw_error[error1-refused-check_listener]` | subsumed | `tests/llm/test_local_connection.py::test_diagnostics_are_fresh_metadata_only_and_never_save_or_select` |
| `tests/llm/test_local_engine.py::test_auto_reads_the_v1_suffix_and_an_explicit_protocol_always_wins[http://ollama:11434/-auto-ollama]` | duplicate | `tests/llm/test_local_engine.py::test_auto_reads_the_v1_suffix_and_an_explicit_protocol_always_wins[http://ollama:11434-auto-ollama]`<br>`tests/llm/test_local_engine.py::test_auto_reads_the_v1_suffix_and_an_explicit_protocol_always_wins[http://host:8000/v1/-auto-openai_responses]` |
| `tests/llm/test_local_engine.py::test_local_budget_is_priced_at_zero_and_keeps_its_own_token_limits` | subsumed | `tests/llm/test_local_runtime.py::test_local_runtime_only_provisions_a_budget_in_dev[dev]` |
| `tests/llm/test_local_inventory.py::test_cpu_measurement_does_not_follow_a_tag_replaced_during_the_run[d2]` | duplicate | `tests/llm/test_local_inventory.py::test_cpu_measurement_requires_a_known_matching_run_digest[d2]`<br>`tests/llm/test_local_inventory.py::test_cpu_measurement_does_not_follow_a_tag_replaced_during_the_run` |
| `tests/llm/test_local_inventory.py::test_cpu_measurement_is_hidden_when_hardware_identity_or_age_changes[change1] ({'vram': 50})` | duplicate | `tests/llm/test_local_inventory.py::test_cpu_measurement_is_hidden_when_hardware_identity_or_age_changes[change0]` |
| `tests/llm/test_local_inventory.py::test_cpu_measurement_is_hidden_when_hardware_identity_or_age_changes[change7] ({'loaded_digest': 'd2'})` | duplicate | `tests/llm/test_local_inventory.py::test_cpu_measurement_is_hidden_when_hardware_identity_or_age_changes[change6]` |
| `tests/llm/test_local_inventory.py::test_cpu_measurement_rejects_unusable_generation_counts[timing5] ({'eval_duration_ms': nan})` | duplicate | `tests/llm/test_local_inventory.py::test_cpu_measurement_rejects_unusable_generation_counts[timing5]` |
| `tests/llm/test_local_inventory.py::test_cpu_measurement_requires_a_known_matching_run_digest[None]` | duplicate | `tests/llm/test_local_inventory.py::test_cpu_measurement_requires_a_known_matching_run_digest[]` |
| `tests/llm/test_local_inventory.py::test_inventory_publishes_current_placement[row2-gpu]` | private-helper | `tests/llm/test_local_inventory.py::test_placement_reads_reported_memory_without_inference[100-gpu]`<br>`tests/llm/test_local_inventory.py::test_inventory_publishes_current_placement[row1-cpu]` |
| `tests/llm/test_local_inventory.py::test_inventory_publishes_current_placement[row3-mixed]` | private-helper | `tests/llm/test_local_inventory.py::test_placement_reads_reported_memory_without_inference[50-mixed]`<br>`tests/llm/test_local_inventory.py::test_inventory_publishes_current_placement[row1-cpu]` |
| `tests/llm/test_local_inventory.py::test_inventory_publishes_current_placement[row4-None] ({'size': 100})` | private-helper | `tests/llm/test_local_inventory.py::test_placement_explains_missing_evidence[models1-ollama_memory_fields_unavailable]`<br>`tests/llm/test_local_inventory.py::test_inventory_publishes_current_placement[row2-None]`<br>`tests/llm/test_local_inventory.py::test_inventory_publishes_current_placement[row3-None]` |
| `tests/llm/test_local_inventory.py::test_inventory_without_answer_models_is_unavailable[models0]` | subsumed | `tests/llm/test_local_connection.py::test_empty_server_is_a_valid_connection_and_changed_url_does_not_get_secret`<br>`tests/llm/test_local_connection.py::test_diagnostics_are_fresh_metadata_only_and_never_save_or_select` |
| `tests/llm/test_local_inventory.py::test_inventory_without_answer_models_is_unavailable[models1]` | subsumed | `tests/llm/test_local_inventory.py::test_discovery_filters_embeddings_and_reuses_details`<br>`tests/llm/test_local_connection.py::test_empty_server_is_a_valid_connection_and_changed_url_does_not_get_secret` |
| `tests/llm/test_provider.py::test_budget_refusal_before_any_validation_carries_no_schema_errors` | merged | `tests/llm/test_provider.py::test_explicit_usage_and_cost_budgets_fail_closed[budget_changes0-response_changes0-input_tokens]` |
| `tests/llm/test_provider.py::test_deterministic_provider_projects_nothing_by_default` | subsumed | `tests/llm/test_provider.py::test_repair_does_not_start_after_the_first_attempt_exhausts_budget`<br>`tests/llm/test_provider.py::test_post_hoc_accounting_is_unchanged_when_the_projection_undershoots` |
| `tests/llm/test_provider.py::test_explicit_model_refusal_is_typed_and_not_repaired` | subsumed | `tests/llm/test_provider.py::test_openai_adapter_maps_structured_refusal_without_network_or_retry` |
| `tests/llm/test_provider.py::test_provider_exception_becomes_typed_error_without_fake_usage` | subsumed | `tests/llm/test_provider.py::test_openai_adapter_rejects_missing_usage_as_typed_provider_error`<br>`tests/llm/test_local.py::test_local_provider_fails_closed_when_usage_is_missing` |
| `tests/llm/test_provider.py::test_strict_format_is_deterministic_between_calls` | subsumed | `tests/llm/test_provider.py::test_repair_loop_still_guards_the_strict_path` |
| `tests/llm/test_provider.py::test_strict_format_keeps_the_reason_bound` | merged | `tests/llm/test_provider.py::test_strict_format_closes_every_object_and_requires_every_key` |
| `tests/llm/test_schemas.py::test_prompt_rejects_whitespace_only_text[system]` | merged | `tests/llm/test_schemas.py::test_prompt_is_strict_frozen_nonblank_and_forbids_unknown_fields` |
| `tests/llm/test_schemas.py::test_prompt_rejects_whitespace_only_text[user]` | merged | `tests/llm/test_schemas.py::test_prompt_is_strict_frozen_nonblank_and_forbids_unknown_fields` |
| `tests/observability/test_persistence.py::test_equal_length_secrets_redact_in_one_stable_pass` | merged | `tests/observability/test_persistence.py::test_redaction_covers_quoted_assignments_explicit_secrets_and_key_collisions` |
| `tests/observability/test_trace.py::test_successful_provider_result_records_no_error` | merged | `tests/observability/test_trace.py::test_provider_results_map_to_traces_with_canonical_refusal_json_or_no_error` |
| `tests/observability/test_types.py::test_schema_refusal_keeps_prompt_and_raw_output_for_audit` | subsumed | `tests/observability/test_persistence.py::test_persistence_mapping_preserves_provenance_and_redacts_secrets`<br>`tests/observability/test_types.py::test_step_trace_is_strict_frozen_and_preserves_raw_output`<br>`tests/observability/test_trace.py::test_provider_results_map_to_traces_with_canonical_refusal_json_or_no_error` |
| `tests/operator/test_lifecycle_receipts.py::test_invalid_receipts_do_not_become_successful_notifications[{"command":"other"}]` | duplicate | `tests/operator/test_lifecycle_receipts.py::test_invalid_receipts_do_not_become_successful_notifications[{"command":"start-fresh","status":"invented"}]`<br>`tests/operator/test_lifecycle_receipts.py::test_invalid_receipts_do_not_become_successful_notifications[broken]` |
| `tests/release/test_01_request_guards.py::test_local_operator_bypasses_public_rate_limit` | merged | `tests/release/test_01_request_guards.py::test_local_operator_bypass_keeps_proxy_marked_requests_metered` |
| `tests/release/test_01_request_guards.py::test_public_custom_retrieval_within_bounds_reaches_the_route[retrieval0]` | duplicate | `tests/release/test_01_request_guards.py::test_public_custom_retrieval_within_bounds_reaches_the_route` |
| `tests/release/test_01_request_guards.py::test_public_custom_retrieval_within_bounds_reaches_the_route[retrieval2]` | duplicate | `tests/release/test_01_request_guards.py::test_public_custom_retrieval_within_bounds_reaches_the_route` |
| `tests/release/test_01_request_guards.py::test_public_proxy_marker_blocks_dev_only_review_policy` | duplicate | `tests/release/test_01_request_guards.py::test_public_prompt_local_and_snapshot_controls_stay_locked[profile2]` |
| `tests/release/test_01_request_guards.py::test_public_proxy_marker_retains_rate_limits_on_a_private_admin_runtime` | merged | `tests/release/test_01_request_guards.py::test_local_operator_bypass_keeps_proxy_marked_requests_metered` |
| `tests/release/test_02_release_app.py::test_live_capabilities_enable_developer_controls` | merged | `tests/release/test_02_release_app.py::test_release_admin_modes_hide_or_enable_the_local_surface` |
| `tests/release/test_02_release_app.py::test_live_operator_disables_only_public_request_limits` | merged | `tests/release/test_02_release_app.py::test_release_admin_modes_hide_or_enable_the_local_surface` |
| `tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[False-dev-live-headers2-True]` | duplicate | `tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[prod-readonly-headers1-True-False]`<br>`tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[dev-live-headers3-True-True]` |
| `tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[False-dev-live-headers3-False]` | duplicate | `tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[prod-readonly-headers1-True-False]`<br>`tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[dev-live-headers4-False-True]` |
| `tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[False-dev-readonly-headers1-True]` | duplicate | `tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[prod-readonly-headers1-True-False]`<br>`tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[dev-readonly-headers2-True-True]` |
| `tests/release/test_02_release_app.py::test_runtime_readiness_returns_typed_200_or_503_without_provider_calls` | merged | `tests/release/test_02_release_app.py::test_runtime_readiness_default_probe_shares_admin_status_and_keeps_the_payload`<br>`tests/release/test_02_release_app.py::test_public_readiness_publishes_counts_and_withholds_only_write_access[prod-readonly-headers1-True-False]` |
| `tests/release/test_ai_allowance.py::test_streamed_actual_call_denial_keeps_error_and_done[False]` | duplicate | `tests/release/test_ai_allowance.py::test_streamed_actual_call_denial_keeps_error_and_done`<br>`tests/release/test_ai_allowance.py::test_concurrent_calls_share_one_request_admission_and_denials_do_not_spend` |
| `tests/release/test_compose_layers.py::test_local_app_shares_host_group_and_writable_creation_mask[1000]` | duplicate | `tests/release/test_compose_layers.py::test_local_app_shares_host_group_and_writable_creation_mask` |
| `tests/release/test_compose_layers.py::test_overlays_declare_no_required_variables[docker-compose.dev.yml]` | subsumed | `tests/release/test_compose_layers.py::test_explicit_development_inherits_the_default_mounts_and_services`<br>`tests/release/test_compose_layers.py::test_compose_modes_inherit_the_image_schema_gate` |
| `tests/release/test_compose_layers.py::test_overlays_declare_no_required_variables[docker-compose.prod.yml]` | subsumed | `tests/release/test_compose_layers.py::test_the_production_overlay_reproduces_the_visitor_build`<br>`tests/release/test_compose_layers.py::test_compose_modes_inherit_the_image_schema_gate` |
| `tests/release/test_config.py::test_operator_key_is_secret_and_only_enables_explicit_runtime` | merged | `tests/release/test_config.py::test_environment_slot_enables_runtime_without_an_explicit_key`<br>`tests/release/test_02_release_app.py::test_release_app_is_canned_healthy_and_nonsecret` |
| `tests/release/test_config.py::test_prod_disables_the_local_engine_even_with_a_complete_endpoint_pair` | subsumed | `tests/release/test_compose_layers.py::test_the_production_overlay_environment_refuses_the_local_engine`<br>`tests/release/test_local_readiness.py::test_development_probes_and_reports_the_model_it_found` |
| `tests/release/test_limiter.py::test_minute_limit_reports_retry_and_recovers` | subsumed | `tests/release/test_limiter.py::test_daily_limit_is_rolling_and_not_a_calendar_reset`<br>`tests/release/test_01_request_guards.py::test_security_headers_and_rate_limit_are_visible`<br>`tests/release/test_limiter.py::test_peek_reports_resets_without_consuming_another_slot` |
| `tests/release/test_local_readiness.py::test_production_blocks_the_default_endpoint` | duplicate | `tests/release/test_local_readiness.py::test_production_names_the_reason_and_never_probes_the_endpoint` |
| `tests/release/test_middleware.py::test_control_denial_preserves_route_validation_ownership[profile7-None]` | private-helper | `tests/release/test_01_request_guards.py::test_public_custom_retrieval_within_bounds_reaches_the_route` |
| `tests/release/test_middleware.py::test_control_denial_preserves_route_validation_ownership[profile8-custom_retrieval.k must be at most 10]` | private-helper | `tests/release/test_01_request_guards.py::test_public_custom_retrieval_above_bounds_names_the_field[retrieval0-custom_retrieval.k must be at most 10]` |
| `tests/release/test_middleware.py::test_control_denial_preserves_route_validation_ownership[profile9-custom_retrieval.candidate_k must be at most 50]` | private-helper | `tests/release/test_01_request_guards.py::test_public_custom_retrieval_above_bounds_names_the_field[retrieval1-custom_retrieval.candidate_k must be at most 50]` |
| `tests/release/test_middleware.py::test_forbidden_preserves_the_public_error_envelope` | merged | `tests/release/test_01_request_guards.py::test_public_prompt_local_and_snapshot_controls_stay_locked` |
| `tests/release/test_public_policy.py::test_limits_expose_public_policy_without_consuming_allowance` | merged | `tests/release/test_02_release_app.py::test_capabilities_and_limit_peek_reflect_release_mode_without_consuming_slots` |
| `tests/retrieval/test_bm25.py::test_corpus_statistics_match_the_fixture` | subsumed | `tests/retrieval/test_bm25.py::test_live_backfill_reproduces_the_fixture_statistics_and_is_idempotent` |
| `tests/retrieval/test_bm25.py::test_document_frequency_counts_documents_not_occurrences` | subsumed | `tests/retrieval/test_bm25.py::test_live_backfill_reproduces_the_fixture_statistics_and_is_idempotent` |
| `tests/retrieval/test_bm25.py::test_length_normalisation_decides_the_top_document` | private-helper | `tests/retrieval/test_bm25.py::test_live_length_normalisation_reverses_the_top_two_documents`<br>`tests/retrieval/test_bm25.py::test_reference_implementation_reproduces_the_committed_fixture` |
| `tests/retrieval/test_bm25.py::test_lucene_idf_stays_nonnegative_for_every_document_frequency` | private-helper | `tests/retrieval/test_bm25.py::test_reference_implementation_reproduces_the_committed_fixture[lucene-0.75-expected_scores]`<br>`tests/retrieval/test_bm25.py::test_live_sql_scores_agree_with_the_python_oracle[lucene]` |
| `tests/retrieval/test_bm25.py::test_public_surface_exports_the_bm25_entry_points` | merged | `tests/retrieval/test_service.py::test_package_exports_the_complete_production_surface` |
| `tests/retrieval/test_bm25.py::test_repeated_query_terms_are_scored_once` | private-helper | `tests/retrieval/test_bm25.py::test_reference_implementation_reproduces_the_committed_fixture` |
| `tests/retrieval/test_bm25.py::test_robertson_idf_goes_negative_and_inverts_the_ranking` | private-helper | `tests/retrieval/test_bm25.py::test_live_robertson_returns_finite_negative_scores`<br>`tests/retrieval/test_bm25.py::test_live_sql_scores_agree_with_the_python_oracle[robertson]`<br>`tests/retrieval/test_bm25.py::test_reference_implementation_reproduces_the_committed_fixture[robertson-0.75-expected_scores_robertson]` |
| `tests/retrieval/test_bm25.py::test_search_executes_once_and_returns_typed_hits` | subsumed | `tests/retrieval/test_bm25.py::test_live_sql_scores_agree_with_the_python_oracle`<br>`tests/retrieval/test_bm25.py::test_search_raises_when_statistics_are_missing_or_stale` |
| `tests/retrieval/test_bm25.py::test_settings_reject_nonfinite_bm25_environment_values[BM25_B-inf]` | duplicate | `tests/retrieval/test_bm25.py::test_settings_reject_out_of_range_bm25_constants[changes5] (bm25_b=inf)` |
| `tests/retrieval/test_bm25.py::test_settings_reject_nonfinite_bm25_environment_values[BM25_B-nan]` | duplicate | `tests/retrieval/test_bm25.py::test_settings_reject_out_of_range_bm25_constants[changes6] (bm25_b=nan)` |
| `tests/retrieval/test_bm25.py::test_settings_reject_nonfinite_bm25_environment_values[BM25_K1-inf]` | duplicate | `tests/retrieval/test_bm25.py::test_settings_reject_out_of_range_bm25_constants[changes1] (bm25_k1=inf)` |
| `tests/retrieval/test_bm25.py::test_settings_reject_nonfinite_bm25_environment_values[BM25_K1-nan]` | duplicate | `tests/retrieval/test_bm25.py::test_settings_reject_out_of_range_bm25_constants[changes2] (bm25_k1=nan)` |
| `tests/retrieval/test_bm25.py::test_settings_reject_out_of_range_bm25_constants[changes1]` | duplicate | `tests/retrieval/test_bm25.py::test_settings_reject_out_of_range_bm25_constants[changes0] (bm25_k1=0)` |
| `tests/retrieval/test_bm25.py::test_statement_applies_every_shared_filter` | duplicate | `tests/retrieval/test_vector.py::test_statement_applies_every_shared_filter_with_and_semantics`<br>`tests/retrieval/test_bm25.py::test_live_filters_narrow_candidates_without_changing_corpus_statistics` |
| `tests/retrieval/test_bm25.py::test_statement_matches_the_relaxed_websearch_query_but_scores_only_positives` | subsumed | `tests/retrieval/test_bm25.py::test_statement_binds_the_query_and_never_interpolates_it`<br>`tests/retrieval/test_bm25.py::test_live_phrase_and_negation_match_like_relaxed_websearch` |
| `tests/retrieval/test_bm25.py::test_statement_rejects_out_of_range_parameters[changes0]` | duplicate | `tests/retrieval/test_bm25.py::test_statement_rejects_out_of_range_parameters[changes0] (query '   ')` |
| `tests/retrieval/test_bm25.py::test_statement_rejects_out_of_range_parameters[changes3]` | duplicate | `tests/retrieval/test_bm25.py::test_statement_rejects_out_of_range_parameters[changes1] (k=0)`<br>`tests/retrieval/test_bm25.py::test_statement_rejects_out_of_range_parameters[changes2] (k=True)` |
| `tests/retrieval/test_bm25.py::test_statement_rejects_out_of_range_parameters[changes6]` | duplicate | `tests/retrieval/test_bm25.py::test_statement_rejects_out_of_range_parameters[changes3] (k1=0)` |
| `tests/retrieval/test_bm25.py::test_statement_scores_from_persisted_corpus_statistics` | subsumed | `tests/retrieval/test_bm25.py::test_live_sql_scores_agree_with_the_python_oracle`<br>`tests/retrieval/test_bm25.py::test_live_chunk_writes_invalidate_statistics_and_search_fails`<br>`tests/retrieval/test_bm25.py::test_snapshot_statement_uses_frozen_membership_and_bm25_statistics` |
| `tests/retrieval/test_cross_encoder.py::test_constructing_reranker_loads_no_model` | subsumed | `tests/retrieval/test_cross_encoder.py::test_empty_candidate_list_does_not_load_a_model` |
| `tests/retrieval/test_cross_encoder.py::test_load_constructs_the_model_once` | subsumed | `tests/retrieval/test_cross_encoder.py::test_simultaneous_cold_scores_construct_one_model` |
| `tests/retrieval/test_cross_encoder.py::test_no_reranker_keeps_baseline_retrieval_behavior` | subsumed | `tests/retrieval/test_service.py::test_service_uses_default_candidate_pool_one_session_and_rank_only_components` |
| `tests/retrieval/test_cross_encoder.py::test_public_surface_exports_cross_encoder` | merged | `tests/retrieval/test_service.py::test_package_exports_the_complete_production_surface` |
| `tests/retrieval/test_cross_encoder.py::test_reranker_rejects_invalid_construction[model--1]` | duplicate | `tests/retrieval/test_cross_encoder.py::test_reranker_rejects_invalid_construction[model-0]` |
| `tests/retrieval/test_cross_encoder.py::test_reranker_rescores_the_full_candidate_pool_then_truncates` | subsumed | `tests/retrieval/test_service.py::test_service_reranks_with_original_query_and_labels_the_score_stage` |
| `tests/retrieval/test_embeddings.py::test_missing_batch_selects_only_missing_configuration_in_stable_chunk_order` | private-helper | `tests/retrieval/test_01_postgres_retrieval.py::test_live_postgres_reuses_exact_inputs_and_guards_vector_configurations`<br>`tests/retrieval/test_embeddings.py::test_backfill_batches_missing_chunks_and_reports_stale_updates` |
| `tests/retrieval/test_embeddings.py::test_settings_require_nonblank_api_key_for_openai_provider[None]` | subsumed | `tests/test_cli.py::test_provider_override_revalidates_the_openai_key_guard` |
| `tests/retrieval/test_embeddings.py::test_settings_require_nonblank_api_key_for_openai_provider[api_key1]` | duplicate | `tests/retrieval/test_embeddings.py::test_settings_require_nonblank_api_key_for_openai_provider (SecretStr('   '))` |
| `tests/retrieval/test_embeddings.py::test_store_batch_guards_current_input_and_preserves_configurations` | private-helper | `tests/retrieval/test_01_postgres_retrieval.py::test_live_postgres_reuses_exact_inputs_and_guards_vector_configurations` |
| `tests/retrieval/test_hybrid.py::test_rrf_keys_identity_by_chunk_id_and_counts_a_list_only_once` | duplicate | `tests/retrieval/test_hybrid.py::test_fuse_ranked_lists_rejects_conflicting_identity_for_one_chunk_id` |
| `tests/retrieval/test_hybrid.py::test_rrf_rejects_nonpositive_limits[-1-60]` | duplicate | `tests/retrieval/test_hybrid.py::test_rrf_rejects_nonpositive_limits[0-60]` |
| `tests/retrieval/test_hybrid.py::test_rrf_rejects_nonpositive_limits[1--1]` | duplicate | `tests/retrieval/test_hybrid.py::test_rrf_rejects_nonpositive_limits[1-0]` |
| `tests/retrieval/test_hybrid.py::test_rrf_rewards_cross_list_agreement_and_ignores_source_score_scales` | subsumed | `tests/retrieval/test_hybrid.py::test_fuse_ranked_lists_generalizes_fusion_to_n_lists` |
| `tests/retrieval/test_korean.py::test_contract_constants_are_pinned` | subsumed | `tests/retrieval/test_korean.py::test_hangul_runs_become_overlapping_bigrams`<br>`tests/retrieval/test_service.py::test_korean_corpus_filter_tokenizes_the_lexical_query` |
| `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[2019 회계연도-ko]` | duplicate | `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[AMD의 매출총이익률은 어떻게 변화했습니까?-ko]` |
| `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[AMD의 매출-ko]` | duplicate | `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[AMD의 매출총이익률은 어떻게 변화했습니까?-ko]` |
| `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[R&D $1,234.5-en]` | duplicate | `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[TSMC 7nm 2021 10-K-en]` |
| `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[ㄱ-ko]` | subsumed | `tests/retrieval/test_language.py::test_detect_query_language_scans_the_declared_unicode_boundaries` |
| `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[ㅣ hello-ko]` | subsumed | `tests/retrieval/test_language.py::test_detect_query_language_scans_the_declared_unicode_boundaries` |
| `tests/retrieval/test_language.py::test_detect_query_language_classifies_on_hangul_presence[가-ko]` | subsumed | `tests/retrieval/test_language.py::test_detect_query_language_scans_the_declared_unicode_boundaries` |
| `tests/retrieval/test_language.py::test_detect_query_language_rejects_blank_input[\n\t]` | duplicate | `tests/retrieval/test_language.py::test_detect_query_language_rejects_blank_input ('   ')` |
| `tests/retrieval/test_language.py::test_detect_query_language_rejects_blank_input[]` | duplicate | `tests/retrieval/test_language.py::test_detect_query_language_rejects_blank_input ('   ')` |
| `tests/retrieval/test_lexical.py::test_module_docstring_names_the_baseline_without_calling_it_bm25` | wording | — |
| `tests/retrieval/test_lexical.py::test_search_executes_once_and_validates_database_mappings` | subsumed | `tests/retrieval/test_01_postgres_retrieval.py::test_live_postgres_reuses_exact_inputs_and_guards_vector_configurations` |
| `tests/retrieval/test_lexical.py::test_statement_applies_every_shared_filter_with_and_semantics` | duplicate | `tests/retrieval/test_vector.py::test_statement_applies_every_shared_filter_with_and_semantics` |
| `tests/retrieval/test_lexical.py::test_statement_handles_an_unnumbered_item_filter_without_an_empty_in_clause` | duplicate | `tests/retrieval/test_vector.py::test_item_null_filter_does_not_emit_an_empty_in_predicate` |
| `tests/retrieval/test_lexical.py::test_statement_parses_the_relaxed_query_once_and_shares_the_materialized_result` | subsumed | `tests/retrieval/test_lexical.py::test_statement_uses_safe_websearch_cover_density_and_complete_hit_projection`<br>`tests/retrieval/test_lexical.py::test_relaxation_distributes_exclusions_and_preserves_phrases_and_explicit_or` |
| `tests/retrieval/test_lexical.py::test_statement_rejects_blank_queries_and_nonpositive_limits[-1]` | duplicate | `tests/retrieval/test_lexical.py::test_statement_rejects_blank_queries_and_nonpositive_limits[   -1]` |
| `tests/retrieval/test_lexical.py::test_statement_rejects_blank_queries_and_nonpositive_limits[valid--1]` | duplicate | `tests/retrieval/test_lexical.py::test_statement_rejects_blank_queries_and_nonpositive_limits[valid-0]` |
| `tests/retrieval/test_rerank.py::test_reranking_rejects_blank_queries_and_negative_limits[-1]` | duplicate | `tests/retrieval/test_rerank.py::test_reranking_rejects_blank_queries_and_negative_limits[   -1]` |
| `tests/retrieval/test_sbert.py::test_constructing_provider_loads_no_model` | subsumed | `tests/retrieval/test_sbert.py::test_factory_builds_configured_sbert_provider_without_loading_model`<br>`tests/retrieval/test_sbert.py::test_empty_batch_does_not_load_a_model` |
| `tests/retrieval/test_sbert.py::test_provider_defaults_match_the_database_column` | subsumed | `tests/retrieval/test_sbert.py::test_factory_builds_configured_sbert_provider_without_loading_model` |
| `tests/retrieval/test_sbert.py::test_provider_rejects_invalid_construction[model--1-32]` | duplicate | `tests/retrieval/test_sbert.py::test_provider_rejects_invalid_construction[model-0-32]` |
| `tests/retrieval/test_sbert.py::test_provider_rejects_invalid_construction[model-384--1]` | duplicate | `tests/retrieval/test_sbert.py::test_provider_rejects_invalid_construction[model-384-0]` |
| `tests/retrieval/test_sbert.py::test_public_surface_exports_sbert_provider` | merged | `tests/retrieval/test_service.py::test_package_exports_the_complete_production_surface` |
| `tests/retrieval/test_sbert.py::test_simultaneous_cold_embeddings_construct_one_model` | subsumed | `tests/retrieval/test_cross_encoder.py::test_simultaneous_cold_scores_construct_one_model`<br>`tests/retrieval/test_sbert.py::test_embed_documents_reuses_the_model_and_runs_model_off_loop` |
| `tests/retrieval/test_scope.py::test_merged_aliases_still_reject_a_different_canonical_owner` | duplicate | `tests/retrieval/test_scope.py::test_normalized_alias_conflict_is_rejected`<br>`tests/retrieval/test_scope.py::test_same_issuer_filings_merge_acquired_and_existing_aliases` |
| `tests/retrieval/test_service.py::test_application_settings_freeze_the_database_dimension_at_384` | subsumed | `tests/test_config.py::test_compose_embedding_dimension_accepts_the_fixed_environment_value`<br>`tests/test_config.py::test_embedding_dimension_still_rejects_other_values[768]` |
| `tests/retrieval/test_service.py::test_english_corpus_keeps_the_raw_query_and_english_config` | subsumed | `tests/retrieval/test_service.py::test_service_uses_default_candidate_pool_one_session_and_rank_only_components`<br>`tests/retrieval/test_service.py::test_translated_variant_keeps_the_target_lexical_lane` |
| `tests/retrieval/test_service.py::test_service_rejects_a_shallow_candidate_pool_with_a_reranker` | duplicate | `tests/retrieval/test_service.py::test_service_rejects_invalid_requests_before_provider_or_search[changes3-at least k]` |
| `tests/retrieval/test_service.py::test_service_rejects_invalid_requests_before_provider_or_search[changes2-positive]` | duplicate | `tests/retrieval/test_service.py::test_service_rejects_invalid_requests_before_provider_or_search[changes1-positive] (k=0)` |
| `tests/retrieval/test_translate.py::test_translate_query_fails_closed_instead_of_returning_the_original` | subsumed | `tests/retrieval/test_translate.py::test_route_query_fails_closed_on_invalid_provider_outputs[not json-None-schema_rejected-2]`<br>`tests/retrieval/test_translate.py::test_route_query_fails_closed_on_invalid_provider_outputs[-Cannot translate this query.-provider_refused-1]`<br>`tests/retrieval/test_translate.py::test_translation_never_reaches_a_network_provider` |
| `tests/retrieval/test_translate.py::test_translate_query_rejects_blank_input_before_any_provider_call[]` | duplicate | `tests/retrieval/test_translate.py::test_translate_query_rejects_blank_input_before_any_provider_call ('   ')` |
| `tests/retrieval/test_types.py::test_chunk_hit_uses_the_canonical_index_text_composer` | subsumed | `tests/retrieval/test_types.py::test_chunk_hit_preserves_the_database_and_citation_surface`<br>`tests/retrieval/test_types.py::test_chunk_hit_accepts_body_as_index_text_when_context_is_empty`<br>`tests/retrieval/test_types.py::test_chunk_hit_rejects_invalid_database_or_runtime_values[changes10]` |
| `tests/retrieval/test_vector.py::test_statement_confines_vector_search_to_snapshot_membership` | merged | `tests/retrieval/test_vector.py::test_snapshot_vectors_require_the_complete_frozen_configuration` |
| `tests/retrieval/test_vector.py::test_statement_rejects_nonpositive_limits[-1]` | duplicate | `tests/retrieval/test_vector.py::test_statement_rejects_nonpositive_limits (k=0)` |
| `tests/test_cli.py::test_python_module_entrypoint_exposes_all_commands` | subsumed | `tests/test_cli.py::test_help_does_not_load_runtime_settings` |
| `tests/test_corpus_admin.py::test_current_ingestion_commands_preserve_explicit_source_modes` | subsumed | `tests/ingestion/test_source_selection.py::test_ingest_selected_job_uses_existing_manifest_job_contract`<br>`tests/test_cli.py::test_ingest_submits_the_shared_job_contract`<br>`tests/api/test_admin_runtime.py::test_acquisition_api_preserves_absent_deletion_and_document_arguments` |
| `tests/test_corpus_admin.py::test_selection_payload_survives_retry_provenance` | private-helper | `tests/test_corpus_admin.py::test_selection_command_restores_from_stored_job` |
| `tests/test_openai_models.py::test_policy_rejects_models_outside_the_role_allowlist[gpt-4.1-mini]` | duplicate | `tests/test_openai_models.py::test_policy_rejects_models_outside_the_role_allowlist[gpt-5-mini]`<br>`tests/test_openai_models.py::test_policy_rejects_models_outside_the_role_allowlist[other]` |
| `tests/test_settings_sources.py::test_dotenv_openai_key_wins_over_process_environment` | subsumed | `tests/test_settings_sources.py::test_process_mode_and_connection_override_dotenv_without_changing_key_order` |
| `tests/scripts/deploy/test_gcp_backend.py::test_archive_rejects_traversal_and_links[../outside]` | subsumed | `tests/scripts/deploy/test_gcp_backend.py::test_archive_rejects_traversal_and_links[corpus/../../outside]`<br>`tests/scripts/deploy/test_gcp_backend.py::test_archive_rejects_traversal_and_links[/absolute]` |
| `tests/scripts/deploy/test_gcp_backend.py::test_first_install_refuses_existing_data[runtime/usage.sqlite3]` | duplicate | `tests/scripts/deploy/test_gcp_backend.py::test_first_install_refuses_existing_data[postgres/PG_VERSION]` |
| `tests/scripts/schema/test_recreate.py::test_permission_preview_offers_exact_owner_fix_before_one_retry[False]` | subsumed | `tests/scripts/schema/test_recreate.py::test_declined_permission_repair_precedes_docker_and_deletion_confirmation`<br>`tests/scripts/schema/test_recreate.py::test_real_unreadable_source_offers_quoted_owner_paths_and_one_retry[False]` |
| `tests/scripts/schema/test_recreate.py::test_permission_preview_offers_exact_owner_fix_before_one_retry[True]` | subsumed | `tests/scripts/schema/test_recreate.py::test_real_unreadable_source_offers_quoted_owner_paths_and_one_retry[True]` |
| `tests/scripts/schema/test_recreate.py::test_wrong_confirmation_never_stops_or_deletes[confirm]` | duplicate | `tests/scripts/schema/test_recreate.py::test_wrong_confirmation_never_stops_or_deletes[yes]`<br>`tests/scripts/schema/test_recreate.py::test_wrong_confirmation_never_stops_or_deletes[]` |
| `tests/scripts/schema/test_sources.py::test_staging_restore_recovers_exact_files_and_manifest` | subsumed | `tests/scripts/schema/test_sources.py::test_command_preserves_sources_on_database_failure[False]` |
| `tests/scripts/stack/test_cli.py::test_no_command_only_shows_help[dev]` | duplicate | `tests/scripts/stack/test_cli.py::test_no_command_only_shows_help` |
| `tests/scripts/stack/test_cli.py::test_start_uses_guided_non_destructive_setup[dev]` | duplicate | `tests/scripts/stack/test_cli.py::test_start_uses_guided_non_destructive_setup`<br>`tests/scripts/test_rag_alias.py::test_start_dispatch_preserves_mode_without_reset[bash-dev]` |
| `tests/scripts/stack/test_fresh.py::test_cancel_every_nonuppercase_gate_without_file_or_docker_writes[answers4]` | duplicate | `tests/scripts/stack/test_fresh.py::test_cancel_every_nonuppercase_gate_without_file_or_docker_writes[answers2]` |
| `tests/scripts/stack/test_fresh.py::test_cancelled_fresh_start_does_not_schedule_browser_reset` | merged | `tests/scripts/stack/test_fresh.py::test_cancel_every_nonuppercase_gate_without_file_or_docker_writes[answers0]`<br>`tests/scripts/stack/test_fresh.py::test_cancel_every_nonuppercase_gate_without_file_or_docker_writes[answers1]`<br>`tests/scripts/stack/test_fresh.py::test_cancel_every_nonuppercase_gate_without_file_or_docker_writes[answers2]` |
| `tests/scripts/stack/test_fresh.py::test_environment_reset_preserves_staged_changes[source.py]` | subsumed | `tests/scripts/stack/test_fresh.py::test_environment_reset_preserves_staged_changes`<br>`tests/scripts/stack/test_fresh.py::test_environment_reset_preserves_dirty_and_untracked_source_work` |
| `tests/scripts/stack/test_fresh.py::test_permission_free_cleanup_does_not_print_a_repair` | merged | `tests/scripts/stack/test_fresh.py::test_environment_reset_preserves_dirty_and_untracked_source_work` |
| `tests/scripts/stack/test_quickstart.py::test_effective_override_cannot_silently_select_fake_embeddings` | merged | `tests/scripts/stack/test_quickstart.py::test_configuration_reports_sources_without_exposing_credentials` |
| `tests/scripts/stack/test_quickstart.py::test_schema_drift_blocks_application_start` | subsumed | `tests/scripts/stack/test_quickstart.py::test_second_schema_failure_cannot_reset_or_start_services` |
| `tests/scripts/stack/test_quickstart.py::test_valid_configuration_is_not_overwritten` | subsumed | `tests/scripts/stack/test_quickstart.py::test_configuration_repairs_the_current_step_without_starting_services[f]`<br>`tests/scripts/stack/test_quickstart.py::test_prod_configuration_uses_prod_key_without_acquisition_credentials` |
| `tests/scripts/stack/test_stack_commands.py::test_completion_does_not_claim_browser_deletion` | merged | `tests/scripts/stack/test_fresh.py::test_environment_reset_preserves_dirty_and_untracked_source_work` |
| `tests/scripts/stack/test_stack_commands.py::test_expired_preview_does_not_start_reset` | merged | `tests/scripts/stack/test_fresh.py::test_preview_expiry_and_file_drift_require_new_confirmation` |
| `tests/scripts/stack/test_stack_commands.py::test_incomplete_reset_never_builds[PermissionError]` | subsumed | `tests/scripts/stack/test_fresh.py::test_post_preview_inode_change_records_failure_without_restart`<br>`tests/scripts/stack/test_fresh.py::test_permissions_are_reported_only_after_failure_and_retried_once` |
| `tests/scripts/stack/test_stack_commands.py::test_incomplete_reset_never_builds[RuntimeError]` | subsumed | `tests/scripts/stack/test_fresh.py::test_post_preview_inode_change_records_failure_without_restart` |
| `tests/scripts/stack/test_stack_commands.py::test_plain_warning_and_noninteractive_guard` | merged | `tests/scripts/stack/test_fresh.py::test_noninteractive_does_not_even_inventory` |
| `tests/scripts/stack/test_stack_commands.py::test_wrong_confirmation_never_starts_reset` | subsumed | `tests/scripts/stack/test_fresh.py::test_cancel_every_nonuppercase_gate_without_file_or_docker_writes[answers2]` |
| `tests/scripts/test_rag_alias.py::test_environment_reset_uses_python_outside_checkout_venv[bash-dev] and [zsh-dev]` | duplicate | `tests/scripts/test_rag_alias.py::test_environment_reset_uses_python_outside_checkout_venv[bash]`<br>`tests/scripts/test_rag_alias.py::test_mode_dispatch_preserves_explicit_actions_and_arguments[bash-dev]` |
| `tests/scripts/test_rag_alias.py::test_explicit_mode_commands_and_registration[bash] and [zsh]` | subsumed | `tests/scripts/test_rag_alias.py::test_mode_dispatch_preserves_explicit_actions_and_arguments[bash-dev]`<br>`tests/scripts/test_rag_alias.py::test_mode_dispatch_preserves_explicit_actions_and_arguments[bash-prod]`<br>`tests/scripts/test_rag_alias.py::test_start_and_destructive_reset_have_separate_help_blocks[bash]` |
| `tests/scripts/test_rag_alias.py::test_mode_without_action_only_shows_help[bash-prod] and [zsh-prod]` | duplicate | `tests/scripts/test_rag_alias.py::test_mode_without_action_only_shows_help[bash]`<br>`tests/scripts/test_rag_alias.py::test_mode_dispatch_preserves_explicit_actions_and_arguments[bash-prod]` |
| `tests/scripts/test_rag_alias.py::test_shell_syntax_and_direct_setup[bash-n\n] and [zsh-n\n]` | duplicate | `tests/scripts/test_rag_alias.py::test_shell_syntax_and_direct_setup[bash]`<br>`tests/scripts/test_rag_alias.py::test_shell_syntax_and_direct_setup[zsh]`<br>`tests/scripts/test_rag_alias.py::test_legacy_filename_registration_is_foreign_state[bash-False]` |
| `tests/scripts/test_rag_alias.py::test_source_registration_help_and_width[bash-80-WORDMARK] and [zsh-80-WORDMARK]` | duplicate | `tests/scripts/test_rag_alias.py::test_source_registration_help_and_width[bash-78-WORDMARK]`<br>`tests/scripts/test_rag_alias.py::test_source_registration_help_and_width[zsh-78-WORDMARK]`<br>`tests/scripts/test_rag_alias.py::test_banner_needs_only_standard_tools[bash]` |
| `tests/scripts/test_rag_alias.py::test_update_rejects_unusable_targets_without_changing_loaded_state[bash-missing---check-updates] and [zsh-...]` | duplicate | `tests/scripts/test_rag_alias.py::test_update_rejects_unusable_targets_without_changing_loaded_state[bash-missing-update]`<br>`tests/scripts/test_rag_alias.py::test_update_rejects_unusable_targets_without_changing_loaded_state[bash-invalid---check-updates]` |
| `tests/scripts/test_rag_alias.py::test_update_rejects_unusable_targets_without_changing_loaded_state[bash-unreadable---check-updates] and [zsh-...]` | duplicate | `tests/scripts/test_rag_alias.py::test_update_rejects_unusable_targets_without_changing_loaded_state[bash-unreadable-update]`<br>`tests/scripts/test_rag_alias.py::test_update_rejects_unusable_targets_without_changing_loaded_state[bash-invalid---check-updates]` |
| `tests/workflow/test_01_node_guardrails.py::test_check_downgrades_supported_when_every_citation_is_fabricated` | merged | `tests/workflow/test_01_node_guardrails.py::test_check_downgrades_a_supported_answer_that_loses_any_citation[every_citation_fabricated]` |
| `tests/workflow/test_01_node_guardrails.py::test_check_keeps_a_supported_answer_whose_citations_all_survive` | merged | `tests/workflow/test_01_node_guardrails.py::test_report_exposes_only_validated_machine_citations` |
| `tests/workflow/test_01_node_guardrails.py::test_grade_with_no_relevant_evidence_returns_typed_threshold_reason` | merged | `tests/workflow/test_02_run_lifecycle.py::test_irrelevant_grade_reports_not_in_docs_without_check_call`<br>`tests/workflow/test_01_node_guardrails.py::test_fixed_absence_notices_follow_the_original_question[irrelevant-*]` |
| `tests/workflow/test_01_node_guardrails.py::test_original_question_controls_response_language_without_changing_retrieval[그럼 2023년은?-...], [NVIDIA 매출을 설명해줘. 답변은 영어로 해줘.-...], [Explain Samsung revenue in Korean.-...], [Explain the term "반도체" in Samsung filings.-...]` | duplicate | `tests/workflow/test_01_node_guardrails.py::test_original_question_controls_response_language_without_changing_retrieval[NVIDIA의 매출 성장 요인은?-What drove NVIDIA revenue growth?]`<br>`tests/workflow/test_01_node_guardrails.py::test_original_question_controls_response_language_without_changing_retrieval[What drove Samsung revenue growth?-삼성전자 매출 성장 요인은?]`<br>`tests/workflow/test_01_node_guardrails.py::test_original_question_remains_inert_json_and_defaults_to_the_workflow_query` |
| `tests/workflow/test_01_node_guardrails.py::test_prompts_quote_evidence_as_data_and_keep_the_system_contract` | merged | `tests/workflow/test_01_node_guardrails.py::test_prompts_quote_the_query_and_evidence_as_data_under_the_system_contract` |
| `tests/workflow/test_01_node_guardrails.py::test_provider_budget_failure_keeps_numeric_evidence` | subsumed | `tests/workflow/test_02_run_lifecycle.py::test_grade_output_repair_limit_preserves_its_actual_source`<br>`tests/workflow/test_02_run_lifecycle.py::test_grade_is_refused_before_the_call_when_its_prompt_exceeds_the_provider_allowance` |
| `tests/workflow/test_01_node_guardrails.py::test_report_without_a_decision_is_not_in_docs_with_typed_reasons` | merged | `tests/workflow/test_01_node_guardrails.py::test_empty_retrieval_is_typed_immutable_and_reports_not_in_docs`<br>`tests/workflow/test_02_run_lifecycle.py::test_no_evidence_short_circuits_both_provider_calls` |
| `tests/workflow/test_01_node_guardrails.py::test_retrieve_empty_is_typed_and_does_not_mutate_input` | merged | `tests/workflow/test_01_node_guardrails.py::test_empty_retrieval_is_typed_immutable_and_reports_not_in_docs` |
| `tests/workflow/test_01_node_guardrails.py::test_runner_requests_more_hits_than_it_will_keep` | subsumed | `tests/workflow/test_02_run_lifecycle.py::test_successful_runner_follows_all_nodes_and_preserves_raw_traces`<br>`tests/workflow/support.py::retriever_returning` |
| `tests/workflow/test_02_run_lifecycle.py::test_a_projected_refusal_is_recorded_without_a_sent_request` | merged | `tests/workflow/test_02_run_lifecycle.py::test_grade_is_refused_before_the_call_when_its_prompt_exceeds_the_provider_allowance` |
| `tests/workflow/test_02_run_lifecycle.py::test_check_allowance_is_clamped_by_the_workflow_budget_not_only_the_provider_one` | merged | `tests/workflow/test_02_run_lifecycle.py::test_check_allowance_is_the_smaller_remainder_of_the_provider_and_workflow_budgets[workflow_clamp]` |
| `tests/workflow/test_02_run_lifecycle.py::test_every_failure_report_keeps_the_degradation_history` | merged | `tests/workflow/test_02_run_lifecycle.py::test_schema_rejection_stops_closed_with_raw_trace_history_and_observer` |
| `tests/workflow/test_02_run_lifecycle.py::test_exact_provider_cost_limit_blocks_check_without_a_second_call` | merged | `tests/workflow/test_02_run_lifecycle.py::test_exhausted_provider_limit_refuses_the_check_before_calling[estimated_cost]` |
| `tests/workflow/test_02_run_lifecycle.py::test_exhausted_provider_token_limit_refuses_the_check_before_calling` | merged | `tests/workflow/test_02_run_lifecycle.py::test_exhausted_provider_limit_refuses_the_check_before_calling[input_tokens]` |
| `tests/workflow/test_02_run_lifecycle.py::test_observer_sees_a_node_that_committed_a_provider_failure` | merged | `tests/workflow/test_02_run_lifecycle.py::test_schema_rejection_stops_closed_with_raw_trace_history_and_observer` |
| `tests/workflow/test_02_run_lifecycle.py::test_provider_allowance_subtracts_prior_tokens_before_check` | merged | `tests/workflow/test_02_run_lifecycle.py::test_check_allowance_is_the_smaller_remainder_of_the_provider_and_workflow_budgets[provider_remainder]` |
| `tests/workflow/test_02_run_lifecycle.py::test_schema_rejection_stops_closed_with_raw_trace` | merged | `tests/workflow/test_02_run_lifecycle.py::test_schema_rejection_stops_closed_with_raw_trace_history_and_observer` |
| `tests/workflow/test_02_run_lifecycle.py::test_spent_token_budget_does_not_discard_a_finished_answer` | merged | `tests/workflow/test_02_run_lifecycle.py::test_successful_runner_follows_all_nodes_and_preserves_raw_traces[exactly_spent]` |
| `tests/workflow/test_gate.py::test_bounded_followups_continue_the_prior_filing_scope[방금 이야기해준거 한글로 다시 설명해줄래]` | duplicate | `tests/workflow/test_gate.py::test_development_demo_matches_routing_rules[followup]` |
| `tests/workflow/test_gate.py::test_clear_roleplay_is_rejected_without_a_model[Pretend you are a cat]` | duplicate | `tests/workflow/test_gate.py::test_clear_roleplay_is_rejected_without_a_model[Pretend Nvidia is a cat and talk to me]` |
| `tests/workflow/test_gate.py::test_exact_service_intents_return_bounded_guidance[안녕하세요], [하이], [hi], [고마워]` | duplicate | `tests/workflow/test_gate.py::test_exact_service_intents_return_bounded_guidance[안녕]`<br>`tests/workflow/test_gate.py::test_exact_service_intents_return_bounded_guidance[hello]`<br>`tests/workflow/test_gate.py::test_exact_service_intents_return_bounded_guidance[감사합니다]` |
| `tests/workflow/test_gate.py::test_followup_form_without_an_anchor_is_not_a_followup` | merged | `tests/workflow/test_gate.py::test_bounded_followups_continue_the_prior_filing_scope` |
| `tests/workflow/test_gate.py::test_known_company_filing_questions_stay_deterministic[삼성의 주가는?]` | duplicate | `tests/workflow/test_gate.py::test_known_company_filing_questions_stay_deterministic[엔비디아의 주가는?]` |
| `tests/workflow/test_gate.py::test_known_company_filing_questions_stay_deterministic[삼전 영업이익]` | duplicate | `tests/workflow/test_gate.py::test_development_demo_matches_routing_rules[shortform]`<br>`tests/workflow/test_gate.py::test_known_company_filing_questions_stay_deterministic[삼성전자 매출]` |
| `tests/workflow/test_gate.py::test_unresolved_targets_are_left_for_the_classifier[Compare Nvidia and SanDisk]` | duplicate | `tests/workflow/test_gate.py::test_development_demo_matches_routing_rules[mixed]`<br>`tests/workflow/test_gate.py::test_unresolved_targets_are_left_for_the_classifier[Nvidia or another company?]` |
| `tests/workflow/test_gate.py::test_unresolved_targets_are_left_for_the_classifier[Nvidia and UnknownCorp revenue]` | duplicate | `tests/workflow/test_gate.py::test_development_demo_matches_routing_rules[mixed]` |

## Second pass: test cleanup audit

This section records the Workflow A2 item 6.6 review of the integrated test-quality
commits. It preserves the earlier tables as historical evidence. The original subagent
removal tables were not recovered from the available scratchpad and task outputs, so this
audit reconstructed each change from its commit and checked the surviving assertions in
the current tests. This was a read-only audit, without test execution. Shared line coverage
or a lower test count alone was not accepted as proof that behavior survived.

The categories follow the second-pass brief: **a**, constant-only; **b**, duplicate;
**c**, implementation pin; **d**, equivalent cases or merged behavioral tests. A rewrite
replaces an assertion about configuration or structure with an assertion about the rule
that consumes it. Removed examples in the same row belong to the same reviewed change;
distinct boundaries and error outcomes are named in the retained-assertion column.

### Count provenance

These are the test-quality pass counts and commit deltas, not final suite totals or the
full branch comparison against `7780a72`.

| Area | Before to after | Evidence and limits |
|---|---|---|
| Ingestion and DB | 549 to 548, reported | Exact commit delta is -1. The original collection totals were not recovered. |
| Retrieval, LLM, agent, observability and workflow | 531 to **509**, conditional | The six cleanup commits remove 23 cases; `9eb612a` restores one facade test. Net delta is -22. If the recorded starting count of 531 is correct, the integrated count is 509; the earlier 508 omits that restoration. Neither absolute collection total was recovered. |
| Scripts, release, operator and top-level | **546 to 530**, recovered | Complete collected-ID logs agree with the -16 commit delta: scripts 346 to 339, release 95 to 91, operator 66 to 64, top-level 39 to 36. |
| API and evals | **576 to 575**, derived after count | Recovered starting IDs contain API 258 and evals 318. Commit deltas are -3 and +2 respectively. The before-run log records 568 passed and 8 deselected; no after-run result is inferred from the count. |
| Corpus admin | Unchanged | All three commits preserve collected cases; no absolute collection total was recovered. |
| Web | **1284 to 1259**, recovered before audit repairs | Per-file lists and passing Vitest logs agree. Restoring the running deletion case adds one case; the resulting 1260 is an expected count, not a final executed result. The long-identifier repair changes no count. |

Recovered logs are rooted at
`/tmp/claude-1000/-home-wwaya-Documents-docreview-rag/8d36a64b-8852-4da7-a12b-0afb81f66d45/scratchpad/`.
The relevant files are `baseline_collect.txt`, `after_collect.txt`, `baseline_ids.txt`,
`baseline_run.txt`, `before-counts.txt`, `after-counts.txt`, `vitest-before.out` and
`vitest-after.out`. The archived integrated Web runs also record 1284 passing cases in
`a2/after/web-ec233bd/logs/test.log` and 1259 in
`a2/after/web-1680605/logs/test.log`. These local logs describe their recorded states;
they do not establish final coverage, evaluation or smoke results.

### Ingestion and DB

Commits: `2dedd5b`, `a96e54f`, `c5f661e`, `fc4d828`, `8f230bb`.

| File and removed or rewritten test | Category | Retained behavior and assertion |
|---|---|---|
| `tests/db/test_session.py`: `test_session_factory_uses_the_shared_engine` | a/c, rewritten | `test_committed_rows_stay_readable_after_the_session_closes` commits through the real factory, checks the returned bind is `engine`, and reads the committed row after the session closes. |
| `tests/ingestion/chunk/test_01_contract.py`: `test_config_defaults_are_positive` | a, rewritten | `test_default_config_plans_with_the_shared_input_budget` checks that the default chunk configuration produces the shared `InputBudget()`, replacing three literal defaults. |
| `tests/ingestion/test_registry.py`: `test_registry_section_codes_never_overlap` | a, rewritten | `test_registry_less_lookup_gives_every_code_its_own_registry_title` checks every SEC and DART code against its own registry's title lookup. |
| `tests/ingestion/test_dart.py`: `test_document_identity_is_explicit_and_not_rederived` | b, merged | `test_parse_dart_filing_maps_registry_identity_without_derivation` now uses the opaque `report-identity` and retains registry, issuer and manifest fiscal-year assertions. |

### Retrieval, LLM and workflow

Commits: `7da67d2`, `b63b340`, `9006bef`, `e45006c`, `3ec4fa4`, `14f320f`, `9eb612a`.
Agent and observability tests have no removals in these commits.

| File and change | Category | Retained behavior and assertion |
|---|---|---|
| `tests/retrieval/test_bm25.py`: statement `k1=inf` case | d | `test_statement_rejects_out_of_range_parameters` retains NaN, zero `k1`, invalid limits, both finite `b` bounds, nonfinite `b` and unknown IDF; invalid statements raise. |
| Same file: settings `bm25_k1=inf` and `bm25_b=inf` cases | d | `test_settings_reject_out_of_range_bm25_constants` retains corresponding NaN cases, zero `k1`, below-zero `b` and above-one `b`. |
| Same file: `test_settings_default_to_ts_rank_cd_with_published_bm25_constants` | a | Literal defaults are removed; settings rejection tests and default lexical service composition remain. |
| `tests/retrieval/test_service.py`: `ComponentRankings.model_fields` set | c | `test_service_uses_default_candidate_pool_one_session_and_rank_only_components` still asserts the complete actual rankings dump, including per-language lanes and chunk identities. |
| Same file: service `bm25_k1=inf` and `bm25_b=inf` cases | d | `test_service_rejects_invalid_requests_before_provider_or_search` retains NaN representatives and the query, limit and candidate-depth boundaries. |
| Same file: facade export-name catalog | c, rewritten | `test_package_reexports_each_public_name_from_its_defining_module` checks a nonempty facade and exact identity with each defining module. The audit established no current guaranteed historical name-set, so it does not require the old catalog pin. |
| `tests/retrieval/test_types.py`: `test_chunk_hit_fields_match_the_current_sqlalchemy_models` | c, rewritten | `test_searched_rows_carry_exactly_the_chunk_hit_fields` compares actual lexical-statement selected columns with the validated hit fields. |
| Same file: `test_chunk_hit_forbids_unknown_fields` | d, merged | `test_chunk_hit_rejects_values_outside_its_contract[unknown-field]` retains rejection of `distance`; invalid identities, spans, content and scores remain separate cases. |
| Same file: `test_language_filters_canonicalize_and_reject_non_tags` | d, merged | `test_filters_are_frozen_and_canonical` asserts sorted, deduplicated languages; `test_filters_reject_invalid_dimensions` retains rejection of `KOR`. |
| `tests/retrieval/test_korean.py`: overlapping-bigram, short-run, particle, Latin/number and mixed-script tests | d, merged | Three `test_tokenizer_emits_the_stored_lexical_tokens` cases assert exact overlapping bigrams, one- and two-character runs, Latin case folding, joined numbers and document order. Particle examples use the same retained bigram rule. |
| `tests/retrieval/test_language.py`: ordinary English sentence | d | `test_detect_query_language_classifies_on_hangul_presence` retains non-Hangul alphanumeric input and Hangul input; Unicode-boundary and blank-input tests remain. |
| `tests/retrieval/test_scope.py`: Samsung `삼전`/`Samsung` and NVIDIA Korean-name/abbreviation examples | d | `test_samsung_aliases_resolve_to_dart_korean` and `test_everyday_company_spellings_resolve` retain manifest names, stock code, short forms, particles, abbreviations and spacing, with issuer, registry and language assertions. |
| `tests/retrieval/test_translate.py`: `not json` route-failure case | b/d | `test_route_query_fails_closed_on_invalid_provider_outputs` retains schema rejection, blank translation, wrong language and refusal with exact attempts. `test_translate_query_fails_closed_instead_of_returning_the_original` and provider repair tests still exercise malformed JSON. |
| `tests/llm/test_local.py`: separate timeout/context-window constructor tests | c/d, merged | `test_provider_accepts_a_positive_timeout_or_window_and_refuses_zero` accepts each positive setting with an owned client, closes it, and matches its zero-value error. Oversized-prompt tests retain operational window enforcement. |
| `tests/llm/test_local_engine.py`: explicit Responses override example | d | `test_auto_reads_the_v1_suffix_and_an_explicit_protocol_always_wins` retains explicit Ollama override plus automatic detection with and without `/v1`, including a trailing slash. |
| `tests/llm/test_provider.py`: `test_provider_boundary_is_abstract_and_async` | c | Awaited `complete()` tests retain typed output, refusal, bounded repair and metadata assertions; abstract-class introspection is removed. |
| `tests/workflow/test_01_node_guardrails.py`: English-original/Korean-rewrite mirror | d | `test_original_question_controls_response_language_without_changing_retrieval` retains the reverse language pair, both grade/check prompts, original-language instructions and distinct unchanged workflow values. |
| `tests/workflow/test_gate.py`: exact-service examples `hello`, `뭐함`, `help`, `사용법` | d | `test_exact_service_intents_return_bounded_guidance` retains exact phrase, punctuation, internal whitespace and casual-cue overlap, each yielding a nonempty `service_help` answer. |
| Same file: `samsung 매출` filing example | d | `test_known_company_filing_questions_stay_deterministic` retains English finance, Korean finance and Korean particles with deterministic `document_review` assertions. |
| `tests/retrieval/test_lexical.py`: rank-normalization constant pin | a/c, rewritten | `test_ranking_normalizes_by_extent_distance_and_document_length` asserts that the actual SQL calls `ts_rank_cd` with its bound normalization equal to `4 \| 1`. |

### API and evals

Commits: `7ad7633`, `039ba89`, `06c5b7a`, `f444e06`, `3ee973a`, `8126113`, `e4d0143`, `e942bed`.

| File and change | Category | Retained behavior and assertion |
|---|---|---|
| `tests/api/test_admin_schemas.py`: `test_default_profile_is_explicit_hybrid_ts_rank` | a | Literal profile defaults are removed. Contradictory strategy/ranker, reranking, routing and candidate-depth cases remain. |
| Same file: duplicate-axis test used the removed `target_text_chars` field | Repaired | `test_matrix_axes_must_be_unique_and_nonempty` now sends duplicate `target_tokens` and matches its uniqueness error, reaching the rule its name promises. |
| `tests/evals/test_parity.py`: language-tolerance literal pins | a, rewritten | `test_language_regression_tolerance_absorbs_one_flipped_case_on_every_metric` accepts one flipped case out of 24 on all gated metrics, rejects a collapse and names recall, hit rate and MRR as regressed. |
| `tests/evals/test_crosslingual.py`: profile filename/selection literals | a, rewritten | Existing CLI-resolution assertions remain. `test_each_corpus_profile_selects_only_its_own_registry_from_the_shipped_manifest` adds two corpus cases requiring nonempty selections exclusively from the intended registry. |
| `tests/evals/test_run.py`: separate strategy and token/ranker axis-normalization functions | d, merged | `test_every_matrix_axis_is_deduplicated_and_canonically_ordered` retains three named cases for strategy, token-target and ranker normalization. |
| Same file: standalone deepest budget-arm example | d, merged | `test_the_budget_arm_is_the_deepest_lane_with_a_ranker_only_for_lexical_queries` retains hybrid precedence, vector's absent ranker and lexical canonical/sole-ranker choices. |
| `tests/evals/test_arms.py`: `test_bm25_values_are_rejected_on_an_arm_that_runs_no_bm25_query` | b | The experiment-config rejection matrix invokes the shared rule and matches `only for bm25 arms` for `ts_rank_cd` carrying a BM25 value. |
| Same file: separate English lexical-lane test | d, merged | `test_lexical_lane_tokenizes_for_the_filtered_corpus_language` retains exact Korean bigrams under `simple` and an unchanged no-filter English query under `english`. |
| `tests/api/test_runtime.py`: supported-question corpus-wide revenue example | b | `test_explicit_corpus_wide_scope_keeps_every_language` reaches retrieval and checks explicit all-corpus scope, unrestricted languages/issuers and zero classifier calls. |
| Same file: supported-question `그럼 2024년은?` example | b | `test_followups_reach_retrieval_with_replaced_scope` retains that exact question, replaced year, inherited issuer/topic and zero classifier calls. |
| `tests/evals/test_ablation.py`: separate missing-BM25 and non-BM25-with-BM25 config tests | d, merged | Both remain in `test_experiment_config_rejects_ambiguous_or_inconsistent_values`, with named cases and exact rule-message matches; existing rejection cases also gain message checks. |
| `tests/evals/test_arms.py` and `test_index_identity.py`: parameter IDs | No removal | All BM25 bind-time and changed-index identity cases remain; IDs name the changed input. |

### Corpus admin

Commits: `029e378`, `48e6cce`, `870662f`. No cases were removed.

| File and change | Retained or corrected assertion |
|---|---|
| `tests/corpus_admin/test_types.py`: zero expected-documents case | Supplies the required selection so validation reaches `expected_documents`, then matches `expected_documents must be positive`. Every other command rejection now matches its intended rule too. |
| `tests/corpus_admin/test_stored_jobs.py`: parameter IDs | All five malformed stored-command cases remain, named after the malformed field. |
| `tests/corpus_admin/test_job_queue.py`: FIFO test name | Submission order and one-at-a-time execution assertions remain; the name no longer claims unasserted progress behavior. |

### Scripts, release, operator and top-level tests

Commits: `c22fa46`, `5d23b9b`, `55ee15a`, `f98a592`, `7f108dc`, `7bad4be`, `0ed8fbc`.

| File and change | Category | Retained behavior and assertion |
|---|---|---|
| `tests/test_atomic_write.py`: umask `022` example | d | `test_mode_is_exact_or_narrowed_by_the_process_umask` still checks actual file modes for exact mode despite umask and umask-narrowed mode. |
| `tests/test_canonical_json.py`: negative infinity | d | `test_non_finite_numbers_are_refused` retains NaN and positive infinity with `ValueError`; exact canonical serialization remains separately checked. |
| `tests/test_openai_models.py`: whitespace-only model | d | `test_policy_rejects_models_outside_the_role_allowlist` retains blank selection and disallowed sibling model with policy-error matching. |
| `tests/test_cli.py`: blank query, zero `k` and absent embedding-provider exit tests | d, merged | `test_invalid_retrieve_arguments_are_typed_invalid_input_exits` retains all three inputs, the exit category and each distinct public error code. |
| Same file: separate provider/database unavailable exits | d, merged | `test_unavailable_dependencies_have_stable_nonsecret_exits` retains both secret-bearing exception fixtures, exact nonsecret error envelopes and `UNAVAILABLE` exit. |
| `tests/operator/test_progress.py`: BM25 single-stage example | d | `test_single_stage_progress_reserves_terminal_completion` retains 99 before postconditions and 100 only after `finish_progress`. |
| Same file: ordinary EDGAR partial-byte example | d | `test_download_bytes_contribute_only_to_acquisition_progress` retains DART completed-item/current-byte combination, EDGAR capping, unknown/zero lengths and non-acquisition exclusion. |
| `tests/operator/test_service.py`: two command-target literals | a | `test_command_targets_match_the_registry_and_live_schema` still compares the full live API target enum with registry targets. |
| `tests/release/test_02_release_app.py`: healthy-prod readiness example | d | `test_public_readiness_publishes_counts_and_withholds_only_write_access` retains degraded-prod, healthy-dev, operator and proxy-marked cases with public counts, redaction and write-access assertions. |
| `tests/release/test_compose_layers.py`: two `test_overlays_declare_no_required_variables` cases | b/c | Dev/prod layer tests actually render Compose with a clean environment, `--env-file /dev/null` and `check=True`, detecting missing required variables through rendering. |
| `tests/release/test_config.py`: default rate/cost literals and exact price estimate | a, rewritten | `test_release_defaults_to_canned_without_provider_activation` retains canned/read-only/provider-off/untrusted-proxy rules and requires the calculated largest default call to fit the per-call cap. |
| `tests/scripts/diagnostics/test_ollama.py`: blocked `invalid` representative | d | `test_shared_blocked_selection_explains_reconnect_without_probing` retains disconnected-server guidance, uncollected inventory and absence of fabricated zero counts or unexpected-response text. |
| `tests/scripts/schema/test_schema_cli.py`: `succeeded` exit-zero representative | d | `test_recreate_cli_maps_explicit_outcomes_without_planning_restart` retains cancelled=0, incomplete=1, exact invocation arguments and prohibition of secondary schema operations. |
| `tests/scripts/stack/test_cli.py`: retired `up`, `down`, `start-quick` examples | d | `test_retired_top_level_commands_are_not_forwarded` retains `start-fresh` parser rejection with exit code 2. |
| `tests/scripts/stack/test_environment.py`: exact loopback address | a, rewritten | `test_defaults_are_complete_and_loopback_bound` checks the loaded host with `ipaddress.ip_address(...).is_loopback`; the complete default environment assertion remains. |
| `tests/scripts/stack/test_quickstart.py`: Compose array representative | b/d | `test_service_states_are_project_scoped` retains JSON-lines reporting. `test_stack_cli.py::test_parse_compose_ps_reads_both_output_shapes` checks actual array and JSON-lines parsing, returned rows, blank output and malformed-shape rejection. |
| Same file: explicit `q` cancellation representative | d | `test_configuration_cancellation_stops_before_database_work` retains default decline and EOF, unchanged dotenv bytes and no later database/setup work. |
| Same file: declined/failed schema-retry functions | d, merged | `test_schema_drift_blocks_application_start` retains both cases: one/two read-only checks, one confirmation and no service start. |
| `tests/release/test_middleware.py`: prompt-override denial example | b | `test_01_request_guards.py::test_public_prompt_local_and_snapshot_controls_stay_locked` retains the exact additional-instructions input and the complete HTTP 403 `capability_disabled` envelope. |

### Web

Commits: `1d9eca0`, `81a2a0e`, `4137ddb`, `8e847ab`, `4fe1b98`, `7d6fcde`, `1680605`.
Paths below are relative to `web/`. The two audit repairs are recorded separately from
the original cleanup decisions; their presence was inspected without running tests.

| File and change | Category | Retained behavior and assertion |
|---|---|---|
| `components/job-history-controls.test.tsx`: dialog timing | Repaired | The focus/Escape test opens inside awaited `act`, then requires the summary and enabled Close button. Focus trap, close and trigger-focus assertions remain. |
| `components/local-engine-settings.test.tsx`: long identifier merged into localized identifier test | b/d, repaired after audit | The retained test again uses 200 repeated characters plus a custom tag, checks the Korean status prefix and preserves the complete option and selected values. The initial merge had shortened the input and lost this boundary. |
| `components/service-shell.test.tsx`: stored-interruption localization test | b, merged | Both locale directions retain translated interruption, canonical persisted English notice and unchanged generated answer. |
| `lib/pipeline.test.ts`: duplicate initial-checking test | b | The live/public parameterized test also asserts pending source and read-only state; every stage is unknown, numberless, actionless and unblocked, with no next action. |
| `lib/company-labels.test.ts`: unspaced Hynix and Hynix bilingual examples | d | Spaced Hynix and Samsung bilingual representatives retain alias normalization and locale-specific labels; unknown-company behavior remains. |
| `lib/i18n.test.tsx`: `ja-JP` example | d | `fr-FR` retains unsupported-locale fallback; `ko`, `ko-KR`, `en-US`, misleading `kok-IN` and empty input remain. |
| `components/slow-cpu-notice.test.tsx`, `lib/local-limit-suggestion.test.ts`, `lib/saved-presets.test.ts`: default literals | a, rewritten | Snapshot the supplied defaults, perform the operation and check full non-mutation. Draft/save behavior, calculated recommendations and prior-copy assertions remain. |
| `lib/documentation-registry.test.ts`: document-count literal | a, rewritten | The development draft must not appear in the ordinary catalog; locale-specific source and route preservation remain. |
| `components/build-workspace.test.tsx`: succeeded/cancelled/interrupted refresh examples | d | Failed-job completion retains exactly one refresh, no repeated refresh on unchanged polling, and matching facets refresh. |
| Same file: running deletion-lock case | Removal rejected and restored | Both queued and running cases prove deletion is enabled without a job, disabled while that job is active, and enabled after it clears, with no preview or submission while blocked. Board counters match the tested status. The interaction exercises the workspace and pipeline guards. |
| `components/job-center.test.tsx`: schema/BM25 placeholder-stage examples | d | The documents representative retains absence of fabricated current-stage progress and preserves recorded overall progress. |
| Same file: DART download-speed example | d | The EDGAR representative retains measured speed and stale/current-item reset behavior. |
| `components/build-pipeline.test.tsx`: deterministic embedding-provider example | d | OpenAI, `none` and null retain the duration note only for embedding execution. |
| `components/retrieval-preset-manager.test.tsx`: Korean/accuracy built-in examples and self-evident ID comparison | a/d | Balanced retains the complete displayed export shape: empty ID, canonical name, description and retrieval settings. |
| `lib/local-models.test.ts`: infinite CPU speed | d | NaN, zero, negative and threshold/fast values retain the no-warning result. |
| `lib/preparation-diagnostics.test.ts`: nine blocked-prerequisite pairs reduced to one | d | The ask-to-embeddings representative asserts blocked state and returns the reported prerequisite. |
| `components/composer-toolbar.test.tsx`: empty block | No assertion removed | All readiness-label assertions remain. |

### Protected regression checks

All **46 named Python regression tests** in the second-pass bug list were found after
correcting one file reference: `test_routes_outside_the_metered_set_never_consume_the_allowance`
was added by `515b052` in `tests/release/test_01_request_guards.py`, not
`test_02_release_app.py`. It remains there, exhausting `/review` to HTTP 429 and then
requiring three `/work` requests to succeed without rate-limit headers. This was a stale
evidence reference, not a removed regression.

The audited test-quality commits remove no live PostgreSQL cases. The two Web corrections
restore the only identified lost boundary and data-loss-prevention scenario within this
audit. The remaining reductions retain the reviewed behavior, rejection paths and
assertions described above; this assertion audit does not substitute for executed final
coverage or integration verification.


## Second pass: integration and verification

The final integration checks use app/script code at `28f8a15`; `00dde96` changes only
coverage-boundary tests. The branch target remains `refactor/remove-dead-code` at
`8ca94d9`, and comparisons use `7780a72`. This continuation integrated the nine review
follow-ups recorded in report section 13.3, completed facade/settings cleanup and restored
lost assertions. It does not present the original authors' checks as independent review.

### Bug and SQL evidence

Report section 13.1 preserves each original defect's commit and regression reference.
Those pre-fix reproductions are inherited from the earlier work; the current unit/live
runs execute the retained regressions. All 46 named Python regression functions remain.
The corrected allowance-test path and the two rejected Web removals are recorded above.

For `f117176` and `4e85ec3`, 64 representative SQL statements were compiled before and
after the shared snapshot-identity predicate and source-ordering extraction. PostgreSQL
and asyncpg SQL strings and bound parameters are byte-identical. Local files are
`sql-before.json`, `sql-snapshot.json` and `sql-ordering.json` under the verification root
`/tmp/a2-continuation-20260926/`; both comparisons passed `cmp`.

### Boundary checks restored or added

`28f8a15` keeps the complete 200-character model name plus tag in rendered status and
selection, and tests both queued and running job deletion locks through the workspace.
Truncating the name makes its test fail. Permitting running-job deletion in both actual
workspace/pipeline guards makes the running case fail; changing only one guard does not
bypass the other. Both app sources were restored byte-for-byte after that experiment.

`00dde96` restores saved `initial` state loading in
`tests/llm/test_local_connection.py::test_default_resolves_runtime_and_legacy_matching_choice_without_writes[stored-initial-state]`.
The removed reset method is not reinstated. The reader must select the configured Default
endpoint, preserve its source and leave the stored bytes unchanged.

The same commit extends existing scenarios for malformed local protocol envelopes and
content parts, mapping-style log arguments and stack redaction, malformed HTTP readiness
bodies, input/cost budget admission, incomplete-turn consistency and invalid reranker
windows. MCP dispatch tests run `main(["--mcp"])` with the real tool registry and a fake
transport, requiring engine release on both normal and exceptional exits. They do not
claim a real MCP transport session.

The eight affected files pass 130 tests under branch coverage. Seven parent-owned and
five agent-owned process-local mutations fail the intended assertions without changing
app/script files: saved-state loading, Responses/Ollama object envelopes, unusable content,
mapping/stack redaction, readiness shape, MCP cleanup, exact input/cost exhaustion,
incomplete-state consistency and a nonpositive reranker window. The temporary mutation
harness has import-rewrite warnings in three agent runs; the normal verification runs
have no warning summary. Mutation diagnostics are separate from the passing suite.

### Coverage preservation and limits

The whole unit/live run is in `cov-final/`. The `cov-verified/` dataset copies that result
and appends the 130 affected tests on unchanged application/script code. It reaches
17,133 of 19,181 statements and 4,271 of 5,456 branches: 89.32% statement coverage,
78.28% branch coverage and 86.88% combined coverage. The report's before/after table uses
these measures separately.

The raw `cov_diff.py` comparator exits **1**, reporting 702 newly missing line numbers and
495 newly missing branch pairs. It compares physical locations, so this is not a clean
mechanical preservation result. Matching unchanged source text reduces the candidates
to two statement locations and zero branches after the saved-state test is restored.
The review also checked all 86 initially changed/moved missing statements and the
197 missing statements/126 missing branches in 25 newly reported modules against their
old owners. New meaningful boundary gaps received the tests above; moved, previously
untested paths and forwarding methods did not receive coverage-only tests.

| Apparent loss | Source/context adjudication |
|---|---|
| `app/evals/snapshots.py:204`, formerly 205 | The baseline records arc 205 to 211 at a line that raises a published-revision error. Its unchanged live test supplies a published revision with a mismatched SHA and exercises the later mismatch error. No assertion was removed. |
| `scripts/schema/recreate.py:104`, formerly 109 | Raw arc 110 to -92 appears in both datasets under the retained live `recreate` test, although that test never calls `local_target`. It is not evidence that the volume-user query lost a test. |
| `app/corpus_admin/inspection.py:536` | The old monolith labels `DocumentDetail` at 855 covered, but its only nearby raw arcs are 1267 to 886 to -878 under the retained ingestion-only live test, which never requests document detail. |
| `app/corpus_admin/operations.py:232` | The same ingestion-only trace labels the old backfill callback covered without requesting backfill. Baseline backfill fakes never invoke that callback. No backfill-progress assertion was removed. |

These are observed source/trace attribution mismatches; their instrumentation cause was
not diagnosed in this product refactor. The source-aware review found no additional
lost behavior assertion, but does not turn the raw comparator into a pass. Detailed local
mapping and adjudication are in `coverage-source-map-verified.json` and
`coverage-adjudication.md` under the verification root. Higher coverage alone is not the
reason any test was removed.

### Evaluation comparison

`run_evals.sh codex26final .../evals` completes every step with exit zero. The database
fingerprints match, and corpus/evaluation-output preservation guards pass. `compare.py`
exits **1** because three of 52 deterministic outputs contain the approved extra empty
`component_rankings.lexical_by_language.ko` list. The other 49 outputs are identical.
A separate strict comparison removes only that empty key from those three probes and
requires the complete remaining objects to equal baseline; hits and all other rankings
match. Five CLI stdout streams are informational text rather than JSON; their JSON
artifacts are compared instead.

All 16 paid decomposition calls return `ok` with the same recorded configuration, and the
single-query arm's metrics match. The unseeded decomposed arm differs: hit rate/recall
0.333333 to 0.250000, MRR 0.141667 to 0.120833. `m3c-02` loses its rank-four hit;
`m3c-22` has different hits with unchanged zero score. The decomposition implementation
diff contains only the module move and typing/import changes. These results are recorded
as variation in the unseeded arm, not equal LLM output or evidence of quality improvement;
generated subquestions were not captured, so an input-by-input causal comparison is not
available. `decomposition-case-diff.json` keys cases by `golden.id`, correcting the generic
comparator's uninformative top-level `None` case key without rewriting its raw output.

### Compose smoke

The repository's base/dev Compose files run as `drr-refactor-smoke-codex26final` with a
fresh database on port 55440 and Web/API proxy on 55441. An isolation-only temporary
overlay replaces `/app/data` with `smoke/app-data` and mounts corpus, profiles, presets
and golden inputs read-only. Existing local settings and usage records are not shared.
The original harness is otherwise preserved in `smoke/run.sh`; no product Compose file
changes are included in this pass.

Readiness, retrieve and review return HTTP 200. Review returns `SUPPORTED` and one citation
to NVDA FY2024 Item 7, following retrieve, grade, check and report, with estimated cost
USD 0.0011389. The citation contains the stored document/source identity and span. The
smoke source-status delta is empty. Teardown is restricted to this disposable project.
This is local Compose evidence, not a deployed-service check.

### Verification commands and artifacts

Every shell invocation used `ulimit -v 4000000`. The final unit command is
`PYTHONPYCACHEPREFIX=/tmp/a2-pycache DATABASE_URL=postgresql+asyncpg://filing:filing@127.0.0.1:55439/filing .venv/bin/python -m pytest -m "not live_postgres" -q -p no:cacheprovider tests`.
The full coverage harness separately provisions isolated PostgreSQL and runs
`-m live_postgres --require-live-postgres`. The three excluded acceptance cases require a
wipe image, a restored public artifact bundle/DSN or prepared local-prod data; skipped or
mocked tests are not substituted for those checks.

`run_web_checks.sh .../web-final` records 1,261 passed tests and zero exits for typecheck,
API generation check, build and post-build typecheck; React/act warnings are absent.
Whole-project basedpyright records 432 files, zero errors and zero warnings. Scoped Ruff,
format checks and `git diff --check` pass. Full unit results and final post-documentation
checks are recorded in report section 13.5 and the delivered PR's verification summary.

## Ultra refactor: current owners and retired formats

This is the expanded, explicitly approved follow-up to section 13, based on `19685bb8`.
Previous second-pass evidence above is historical and is not rewritten as evidence for
these new edits. Local records are under `/tmp/pr221-ultra-20260926/`, with bounded-agent
reviews in `/tmp/pr221-{api,llm,web}-review.md` and `/tmp/pr221-final-independent.md`.
Every shell check used `ulimit -v 4000000`. No user database or stored runtime artifact was
used as a disposable fixture. Old stored-format support was explicitly retired by the
user; unsupported data is not silently repaired and its original bytes are not deleted.

### Removal decisions and independent review

Reviewer names below identify distinct non-author reviewers: coordinator (R), API/jobs
(A), LLM/evaluation (L), Web (W), and fresh independent consumer review (I). The evidence
is actual producer/consumer inspection, not simply absence from a text search. Framework
routes, CLI roots, stored writers, imports and current test assertions were included.

| Removed owner/path | Current owner and reachability evidence | Independent verdicts |
|---|---|---|
| Duplicate settings fields/validators/key caches; deprecated environment/key aliases | Both settings classes inherit `ProviderSettings`; all release callers use `service_mode`; current Compose still selects `MODE` and `DOCREVIEW_MODE` separately. | A, W, I: remove |
| Readiness board projection and swallowed lookup errors | Measurement uses its submitted job ID; standalone probes need no admin board. | A, W, I: remove |
| Inferred ProviderMetadata/StepTrace requests; retired chat node | Current providers and trace conversion supply explicit requests; no current workflow emits chat. Sparse current DB trace encoding remains. | A, W, I: remove |
| Historical Trace reconstruction/matching in usage and execution | Provider completion records current calls; runtime captures explicit `model_calls`, including empty provider-free lists. | R, A, W, I: remove |
| Local connection v1 reader | Current writer emits v2; initial/default/disabled/server selection reads v2. Invalid or unsupported bytes remain untouched. | R, A, W, I: remove |
| CorpusOperationRequest wrapper and duplicate validation | Route, CLI, persistence and retry share strict-scalar `AdminCommand`; JSON arrays still become tuple selections. | R, W, I: remove |
| Corpus shadow JobBoard/history, stored-job projection and forwarding methods | API history already reads durable JobStore; queue retains active work until persisted completion. | R, W, I: remove |
| Inspector document-detail SQL/projection/types | Admin now uses DocumentCatalog(public_only=False); public path retains filtering and sanitized URLs. | R, W, I: remove |
| Wrapperless wipe-journal reader | Current atomic writer always emits result and lease fields; unsupported old bytes reject without deletion. | R, W, I: remove |
| Duplicate artifact readers/indexers and private cross-service forwarding | EvaluationArtifacts confines paths before inspection; shared indexing rejects duplicate/missing IDs. | R, W, I: remove |
| Persistence scoring repair and sequence-only retrieval adapter | Evaluator writes actual scoring once; every adapter returns hits with its optional per-call decomposition evidence. | R, W, I: remove |
| DB golden revision/builtin fallback, snapshot revision fields, constant file response fields | No app/scripts DB revision writer; current file owner emits draft/validated. Evaluator records bound-case hash; all readers verify it directly. File-copy request parent_id remains current. Physical schema is unchanged. | R, A, I: remove |
| Web incomplete-profile/old progress repair, free-text budget inference and retired labels | Current writers emit full profiles/progress, typed budgets and required operator target. Recovery preserves rejected originals before replacement. | R, A, I: remove |
| Web duplicated terminal projections and flat/wrapped ambiguity | SSE emits flat RunResponse; current admin preview still explicitly emits {profile, run}. Shared lifecycle preserves request identity and cancellation. | R, A, I: remove |
| Unreachable Measure public branches, duplicate refresh and mutable builtin catalog | Public workspace owns visitor pages; one job-signature effect refreshes runs; explicit current catalog drives server defaults. | R, A, I: remove |

### Per-test disposition

The Python names below are the complete baseline-to-final removed-name inventory; several
were renamed or moved. Parameters and assertions for supported behavior are retained.

| Baseline test (module shortened) | Disposition and retained behavior |
|---|---|
| admin_runtime: `test_document_detail_checks_schema_before_serializing` | Removed wrapper-only test; catalog drift test checks the actual gate before all document reads; isolated PostgreSQL checks public/admin parity. |
| admin_runtime: `test_job_board_reads_history_without_revalidating_ingestion_arguments` | The first deletion also lost actual unified-board coverage. Source-aware comparison caught it; `test_operator_board_reads_persisted_history_and_global_queue_actions` restores current history, FIFO positions, cancellation/retry rules and fresh-instance detail reads. Only the old incomplete-command premise is retired. |
| admin_schemas: `test_exact_ingestion_and_current_cli_manifest_requests_remain_valid` | Actual HTTP route test proves exact IDs, array/tuple roundtrip and same command instance at enqueue. |
| admin_schemas: `test_selected_ingestion_requires_nonempty_unique_document_ids` | Actual HTTP invalid-command cases retain empty/duplicate IDs plus strict scalars and unknown-field rejection. |
| admin_schemas: `test_source_deletion_requires_a_dedicated_explicit_confirmation` | Same HTTP cases and domain tests retain dedicated confirmation and exact selection before enqueue. |
| job_queue: `test_historical_ingestion_without_selection_is_refused_on_retry` | Current stored-job incomplete-command test retains rejection before execution; queue tests now read the real ledger contract. |
| public_snapshot_details: `test_artifact_only_snapshot_is_hash_verified` | Current canonical artifact test checks key-order independence and no old DB revision reads. |
| public_snapshot_details: `test_historical_source_bound_artifact_requires_exact_original_and_frozen_source` | Real custom file -> binding -> evaluator -> public reader covers original-file preservation and altered question/source, missing frozen source and missing identity rejection. |
| public_snapshot_details: `test_version_one_scoring_stamp_matches_persisted_configuration` | Current evaluator/artifact/ORM-row/public-detail roundtrip replaces unsupported old scoring repair; changed cutoff, threshold and retrieval config reject. |
| regression: `test_a_config_cannot_shadow_the_reserved_scoring_stamp` | Moved to evaluator owner and proves rejection before retrieval. |
| local_connection: `test_corrupt_file_fails_closed_and_prod_does_not_read_or_probe` | Renamed invalid-format test adds v1 connected/disabled rejection and exact byte preservation; PROD still neither reads nor probes. |
| local_connection: `test_default_resolves_runtime_and_legacy_matching_choice_without_writes` | Current saved-initial test retains v2 default selection without writes; only v1 matching-address case retired. |
| llm/schemas: `test_provider_metadata_keeps_final_raw_output_and_retry_count_consistent` | Consolidated into explicit-count test retaining final output, blank provider, repaired count, mismatch and zero-request denial assertions. |
| observability/types: `test_step_trace_counts_sent_requests_and_defaults_older_records_to_their_attempts` | Explicit one/two/zero request cases remain; missing count now rejects. Current sparse persistence roundtrip remains. |
| usage: `test_model_calls_include_gate_without_double_counting_the_same_trace` | Real deterministic provider plus stage recorder verifies gate, repair and unsent denial counts [1,2,0], exact tokens and cost. |
| usage: `test_old_unpriced_calls_and_local_estimates_remain_explicit` | Unsupported incomplete call half retired; local embedding unknown-input/zero-cost assertion retained separately. |
| usage: `test_partial_model_calls_keep_unmatched_historical_traces` | Retired reconstruction; malformed current lists reject and actual producer records retain all attempts. |
| usage: `test_stored_rows_without_call_records_reconstruct_their_sent_requests` | Retired reconstruction; missing list rejects, explicit [] is provider-free, persisted current usage is integration-tested. |
| operator/commands: `test_readme_command_table_matches_the_executable_registry` | Archived wording oracle removed; fixed argv, excluded/destructive targets, timeout and confirmation behavior remain. |
| readiness: `test_percentile_uses_nearest_rank_and_tolerates_empty_input` | Summary test uses independently fixed p95 values; all-failed samples still exercise empty latency handling. |
| readiness: `test_phase_tags_follow_the_queued_job_status` | Actual HTTP job-detail responses cover queued/running/succeeded and lookup failure instead of removed projection helper. |

Web removals: stored chat node/old casual intent, operator response without required target,
and incomplete saved-profile migration assert retired shapes. Current service-help,
committed-stage, failure/cancellation, typed budget and complete-profile behavior remain.
The direct terminal-helper auth-text assertion duplicated retained pipeline classification;
real stream failure and selected-evidence lifecycle checks remain. Provider timing fixtures
now use the sole current field with the same speed/zero-duration/missing-data assertions.
DEV/PROD mounted-shell recovery tests prove original bytes survive startup autosave, and
preset tests prove DEV defaults cannot pollute PROD. No test file was deleted.

Protected boundaries are still executed: long local-model names in
`local-engine-settings.test.tsx`, both queued and running deletion locks in
`build-workspace.test.tsx`, saved initial v2 connection state, billed-attempt metadata,
pre-call/repair refusals, unrestricted multilingual search and shared reranker lifetime.
Constant-test scan found no constant-only Python tests; mixed schema/behavior checks were
kept. Coverage overlap alone was not used to remove tests.

### Repairs found by the final broad gates

The first broad unit run reported 2,191 passed, 3 failed, 40 skipped. The snapshot resource
fixture still passed a removed field, one offline queue test relied on the removed implicit
fake-store behavior, and cross-language parity treated the newly recorded case digest as
a shared retrieval setting. The first two now use the current schema and explicit LedgerStore.
Parity compares the same suite, cutoff, all/scored case IDs and retrieval/scoring settings
while excluding the language-specific evaluated-case hash. The actual evaluator test proves
the two hashes differ and the valid language pair still passes. Same-language baseline
comparison retains the hash. The API reviewer independently checked this distinction.
All evaluation tests plus affected API/source-selection tests then passed: 369 passed,
4 live tests deselected. This reuses unchanged full-suite results, rather than claiming a
second complete unit run.

The first required PostgreSQL run reported 34 passed, 4 failed. One fixture supplied old
trace-only usage data; it now supplies current recorded calls with unchanged fixed expected
request/token/cost totals, and passes on a new isolated database. Three failures stopped at
missing acceptance-environment guards: wipe image, restored public bundle/DSN, prepared
local-PROD data. Their actual acceptance procedures remain not run; they are not reported
as passing or silently reclassified as skips. No user database was touched.

Web snapshot type integration initially failed because a fixture lacked the API's required
raw_artifact_path. Using the generated resource exposed that missing field; the current
fixture now supplies it. The original failed type/build logs are retained alongside the
subsequent passing checks. Initial Python type errors likewise identified obsolete snapshot
arguments and a nullable execution assertion; both are corrected without relaxing types.

The coverage comparison additionally identified a removed unified-board execution path.
The restored behavioral test passed all three running-job variants; the whole affected
module passed 11 tests. The JobStore domain filter lost its incidental caller when the
shadow corpus board was removed, so the existing mixed-domain PostgreSQL test now asserts
that filtering includes its evaluation row and excludes its corpus row. This strengthens
the current owner rather than restoring the obsolete board.

### Coverage method and attribution limits

The pre-ultra reference is the preserved `cov-verified` dataset in
`/tmp/a2-continuation-20260926/`: 17,133/19,181 statements (89.3228%) and
4,271/5,456 branches (78.2808%). The new broad dataset is retained unchanged in
`coverage-final`, including every failure. `coverage-verified` reuses unchanged production
files and appends only repaired/affected tests. Since parity source changed after the broad
run, its old arcs were explicitly purged with coverage.py's `CoverageData.purge_files`
before all evaluation tests were recollected; stale line numbers are not merged for that
file. Test-only fixture changes do not change measured production locations.

Source matching against `19685bb8` initially found 11 formerly covered statements and two
branch pairs missing. Eight statements belonged to the deleted unified-board test and were
restored by the current-format board test. The live domain-filter assertion replaces an
incidental filtered-list call removed with the shadow board. The other two locations are
not evidence of removed valid assertions:

- `CorpusJobQueue.enqueue`'s full-queue raise was attributed to the unchanged live ingestion
  test, which enqueues three jobs sequentially and joins each before the next. It never
  fills the queue. No queue-capacity assertion was removed by this change.
- `_persist_current_job`'s return was previously reached when the optional store was None.
  That supported test-only branch is retired; the current store is required. The remaining
  missing-job guard has no lost historical assertion. Progress, failed persistence and
  final flush behavior remain tested at the durable store boundary.

The 16 changed/moved missing statements were inspected separately: existing malformed-v2
connection guards, moved artifact/schema error paths, single forwarding lines and
unexercised adapter/cancellation branches. None justified replacing real assertions with
coverage-only calls. Aggregate coverage and this attribution review do not turn the old
raw location comparator's exit 1 into a mechanical pass or diagnose its instrumentation.

### Historical LLM decomposition decline: independent causal check

The retained before/after artifacts contain 16 total and 12 scored positive cases. The
entire aggregate decrease is one case, `m3c-02`, moving from first relevant rank 4 to no
hit: recall/hit rate 0.333333 -> 0.250000 and MRR 0.141667 -> 0.120833. `m3c-22` also
changes returned hits but remains a miss. All 16 single-query hit/score records match.
The old generic comparison's `None` case IDs were not used; this check joins actual
`cases[].golden.id` and inspects the corresponding scores.

The fresh reviewer compared base `8ca94d9`, pre-ultra `19685bb8` and current code. The
applicable system prompt, structured schema, original questions, 1,000/300 token and
USD 0.05 call budget, explicit Terra model, Responses arguments/medium reasoning, ordered
subquestion dispatch, RRF fusion and sequential case pairing are unchanged. The CLI's
older default-model change cannot explain these runs: the harness explicitly passes the
model, and both sets of 16 logs record Terra, status ok and one request. Equal corpus
fingerprints contain only 2,567 English chunks, so the additional empty Korean lexical
lane cannot change these rankings. No changed scoring arithmetic or case/hit join was found.

All input-token counts match; six output-token counts differ, including `m3c-02` at
99 -> 137. That is evidence of different provider usage, not proof of particular generated
text. Historical subquestions and raw responses were not captured, so their exact semantic
difference, provider-side state or model revision cannot be reconstructed or replayed.
The evidence points to the generated decomposition boundary without establishing its exact
cause; calling it random variation would exceed the evidence. No new paid evaluation was run.

Current `EvaluationRetrieval` stores the actual decomposition from the same awaited call
with that case's hits, including the provider-status reason for fallback. No second call
or question-string lookup is added. The repeated-question/distinct-case regression checks
exact recorded subquestions, fixed fused order [2, 1] and explicit fallback result [3].
This improves future attribution and does not claim to recover the missing historical
record or improve the measured recall.

### Final verification record

Evidence is retained under `/tmp/pr221-ultra-20260926/`; the reference artifacts remain
under `/tmp/a2-continuation-20260926/`. Commands ran with `ulimit -v 4000000` and no paid
provider opt-in. The final checkout contains 154 changed tracked paths, no deleted files,
and no changes to instruction/OPS files, physical DB schema, stored data or dependencies.

| Check | Final result and evidence |
|---|---|
| Python broad unit gate: `pytest -m "not live_postgres" --cov=app --cov=scripts --cov-branch --cov-context=test` | Initial 2,191 passed, 3 failed, 40 skipped; immutable `coverage-final/unit.xml` and logs retain all outcomes. The three failures were repaired as described above. |
| Affected Python rerun: `pytest -m "not live_postgres" tests/evals tests/api/test_01_resource_reads.py tests/api/test_execution.py tests/ingestion/test_source_selection.py` | 369 passed, 4 live cases deselected (`unit-repair.xml`). Restored current board behavior and its whole module: 11 passed, 2 live cases deselected (`board-verified.log`). Final collection selects 2,237 unit cases, including the 40 skips; no second full-suite pass is claimed. |
| Actual isolated PostgreSQL: `pytest -m live_postgres --require-live-postgres` | Initial 34 passed, 4 failed (`coverage-final/live.xml`). The current usage-persistence fixture passes on a new isolated database (`live-repair.xml`), giving passing evidence for all 35 supported live checks. The strengthened existing mixed-domain JobStore test separately passes (`live-domain.xml`). All temporary databases were sequential, disposable tmpfs containers; no user database was used. |
| Environment acceptance | Three environment guards still fail: wipe image, restored public bundle/DSN, and prepared local-PROD data. The guarded acceptance operations were not run. These remain failed guards / unrun operations, not passing or skipped evidence. |
| Python static checks | Ruff check and format check pass on all 95 changed Python files (`ruff-delivery.log`). Basedpyright checks 432 files with zero errors/warnings (`basedpyright-post-repair.json`); the later board/domain test changes have separate zero-error checks. `git diff --check` passes. |
| Web broad gate: `npm test -- --maxWorkers=2`, `npm run typecheck`, `npm run check:api`, `npm run build`, post-build typecheck | 1,263 tests in 223 suites pass without React/act warnings (`web-final/summary.json`). After the final snapshot delta, 84 affected tests pass; type/API/build/post-build checks pass again (`web-snapshot-repaired/summary.json`). The final golden-fixture-only change passes its 3 tests. Earlier fixture type/build failures remain recorded. |
| Deterministic evaluation | All 14 harness steps exit 0. Of 51 comparable deterministic outputs, 9 match exactly and 42 differ only by the newly added `config.scoring` and `config.evaluated_golden_sha256`. Removing only those newly added keys leaves every prior field, hit, score and rank equal (`evaluation-comparison.json`). The separate informational budget output also matches. |
| Evaluation evidence integrity | All 42 raw case artifacts independently reproduce their stored canonical case hash, unique case IDs and scoring parameters `k=5`, `coverage_threshold=0.5` (`evaluated-artifact-verification.json`). Corpus/DB fingerprints match; corpus files, profiles and existing eval-run listings are unchanged. |
| Evaluation comparison limits | Five existing CLI stdout files contain non-JSON output and remain unreadable to the JSON comparator; their individual arm artifacts are compared. The paid decomposition block was excluded, including its paired baseline and stdout (three outputs). No new paid evaluation was run. |
| Browser/Compose/deployment | No new browser or Compose smoke, deployment, merge or real-service verification. Earlier section-13 smoke belongs to the earlier head and is not presented as final-head runtime proof. |

The final combined coverage is **16,925/18,834 statements (89.8641%)** and
**4,212/5,316 branches (79.2325%)**, versus 89.3228% and 78.2808% before this follow-up.
The source-aware comparison now leaves two matched statements and one branch pair in
`job_queue.py`, covered by the explicit attribution limitations above; the board and domain
filter gaps are closed. Sixteen changed/moved missing statements retain their separate
inspection disposition. The raw physical-location comparator is not claimed to pass.

These are reviewer-authored repairs and implementation checks, supported by bounded
independent agent reviews; they are not independent human approval. Historical LLM
decomposition causality and the three unrun acceptance environments remain unresolved.

## Post-integration job history verification

The user requested the existing implementation PRs be merged first, followed by fixes for
exact job-ID lookup and evaluation history ownership. PR #221 merged at `fe280f36`, then
#220 at `12bccbbb`; both preserve verified tree `089774d949cace85cdd795701d780a848599f875`.
Local main was clean and fast-forwarded. Living drafts #37/#38 and other worktrees remain.
The follow-up starts from `12bccbbb` and does not change DEV/PROD policy or browser code.

### Removal and behavior evidence

| Removed path | Actual reachability and retained responsibility | Independent non-author verdicts |
|---|---|---|
| Single-job lookup through the recent 100-job board | The ID route and retry/cancel response paths need an exact persisted record, not a bounded presentation page. `JobStore.get` now owns that read; archived terminal records remain hidden. Queue positions read every queued ID in coordinator order. | API reviewer, LLM/search reviewer, final reviewer: remove |
| Evaluation `_history` and `_hydrate_jobs` | The deque only received/filtered IDs and did not own ordering or evict execution state. Startup hydration was the sole producer of the stale terminal cache. `jobs()` now projects current `JobStore.list(domain="evaluation", limit=20)` rows. | Coordinator, LLM/search reviewer, final reviewer: remove |
| Evaluation `forget_history` | Its only caller invalidated terminal cache after API deletion. Ledger reads now reflect archive, restore and deletion directly; the callback is removed with its caller. | Coordinator, LLM/search reviewer, final reviewer: remove |
| Evaluation `job()` and no-store execution branch | No application, script, export or registered route called `job()`; tests used it instead of the live list contract. The served constructor already supplied `JobStore`. Offline tests now inject `LedgerStore`; runtime construction defaults to a real store. | Coordinator, LLM/search reviewer, final reviewer: remove |
| Cached retry and retained terminal execution state | Retry validates one persisted request and preserves its original row and `retry_of` link. `_jobs` remains for active deduplication, cancellation and progress, then is released after pending writes finish. Recovery still interrupts stale work once and never resumes it automatically. | Coordinator, LLM/search reviewer, final reviewer: remove |

No existing test was deleted or skipped. Queue completion, shared execution ordering,
preparation rechecks, duplicate rejection, delayed progress versus cancellation, restart
interruption, effective BM25 settings and recorded result references remain asserted.
Test reads moved from the deleted cache accessor to the actual persisted-list contract.
The new rejection cases distinguish missing/archived/wrong-domain records and current
queued/running/succeeded/cancelled states from eligible failed/interrupted retries.

Both defects reproduced before their production fixes: old job-ID reads returned None
after 100 newer rows (three existing parameter cases), and an evaluation archived at
startup stayed absent after restoration. The extended API test retains all prior history,
queue-action and missing-ID assertions. The evaluation test verifies restored request,
status, progress, result IDs, baseline and artifact references, then re-archive/removal.
Actual PostgreSQL independently exercises archive before service creation, restoration
through `JobHistoryService`, and the next read from that same evaluation service.

Two test assumptions were corrected during review: an old restart fake returned oldest
first instead of `JobStore.list`'s newest-first order; the new current-state retry test
initially seeded queued/running records before recovery. It now completes empty-store
recovery before seeding current work, keeping restart interruption and active-job refusal
separate. No production behavior was changed to accommodate either fake.

### Final checks and limits

Evidence is under `/tmp/job-history-reads-20260926/` and the implementation/removal audit
is `/tmp/job-history-evaluation-review.md`. Every shell command used `ulimit -v 4000000`.

- **Unit:** `pytest -m "not live_postgres" tests/api tests/evals tests/operator
  tests/corpus_admin tests/scripts/diagnostics` passes **737 tests**, with 17 live cases
  deselected (`unit-final.xml`). The initial broad run had 736 passed/1 failed because
  an offline route fixture omitted its ledger. Explicit injection repaired it without
  restoring a no-store runtime path; its module passed 28 before the final broad rerun.
- **Actual PostgreSQL:** seven job/history/API checks pass (`live-final.xml`), including
  exact FIFO ties, state transitions, archive/restore, backup/delete protection and current
  result metadata. Three additional usage/source checks pass (`live-coverage.xml`) to
  recollect unchanged SQL paths in the edited modules. The first live launch omitted two
  dedicated fixture DSNs and stopped at their guards (5 passed/2 failed); its logs remain.
  The corrected harness created the missing disposable databases. All DB writers ran
  sequentially on owned tmpfs containers, which were removed afterward.
- **Static:** Ruff check/format passes for all ten changed Python files. Basedpyright
  checks 432 files with zero errors/warnings; the subsequent test-only corrections also
  pass their scoped type checks. `git diff --check` passes.
- **Coverage:** unchanged production files reuse the prior verified dataset. Old arcs
  for `admin_runtime.py`, `evals/admin.py` and `operator/jobs.py` were purged before the
  affected tests were recollected. Final statements: **16,919/18,795 (90.0186%)**, versus
  89.8641%; branches: **4,201/5,278 (79.5945%)**, versus 79.2325%. Source-aware matching
  against `12bccbbb` finds **zero previously covered unchanged statements or branches
  missing**. One changed scheduling line remains unexecuted; its former optional-store
  branch was also unexecuted. No coverage-only assertion was added to hide that limit.
- **Not run:** full-repository unit suite, Web checks, generated API rebuild, browser,
  Compose, paid/provider evaluation, deployment and unrelated acceptance environments.
  Public schemas, Web sources and retrieval/scoring implementations are unchanged.

The existing terminal-write failure policy is preserved: after bounded persistence
attempts fail, the last durable state remains authoritative; unfinished records become
interrupted on restart. The follow-up does not claim storage recovery after an unavailable
database or alter the user's intentionally different DEV/PROD data-reading policies.


## Final state ownership and acceptance verification

Scope starts at main `8833ff46` after #222. Local artifacts are in
`/tmp/final-three-20260926/`; prior runs remain unchanged. The user approved all three
remaining items and the PR-to-merge-to-clean-main delivery sequence. This section records
new evidence and does not rewrite earlier failed or unrun results.

### Profile ownership and test integrity

Only the active conversation supplies mutable session settings. The removed shell state
was initialized to `DEFAULT_SESSION_PROFILE`, copied whenever a conversation was selected,
and patched alongside that same conversation. Before capabilities initialize the list,
there is no active record to edit; those temporary edits were already discarded by the
old initialization. Current rendering uses the immutable default until the list exists.
`updateSessionProfile` then patches the active ID in the latest functional state, keeping
messages appended by an in-flight response.

The Web author changed `service-shell.tsx` and extended two existing tests. New/reopen/delete
checks retain the original conversation-message assertions. Delayed-capabilities checks
retain the prohibition on administrator/local calls before capabilities, then assert the
saved profile survives and later edits preserve messages. Existing submitted-profile,
streaming, cross-conversation response and PROD projection cases are retained. No test was
removed or weakened; no failing-before behavior is claimed for this refactor.
Three non-author reviews (coordinator, final reviewer, LLM/search reviewer) independently
accepted the removal. These are agent reviews, not independent human approval.

### Actual acceptance and runtime results

| Check | Result and bounded meaning |
| --- | --- |
| Focused Web integration | 88 passed in `web-service-shell.log`. |
| Full Web suite, maximum two workers | 1,263 tests / 121 files passed in `web-full.log`; no additional tests were collected. |
| Web typecheck | `tsc --noEmit --incremental false` passed; `web-typecheck.log`. |
| Fresh application image | Actual `docker/Dockerfile` build, canned public Next bundle, passed; `image-build-authorized.log`, image `drr-final-validation:20260926`, config SHA256 `2a359ef180f320a42c167eb69144fc9c500ced783852ac803cc71edae8aff671`. Application/Web source matches the final change; later edits affect only tests and these reports. |
| Public dump restore | `test_restored_public_portfolio_matches_checked_artifacts` passed against localhost `pipeline_test_restore`, freshly bootstrapped from current ORM and populated from the verified public dump; `public-restore.xml`. |
| Local PROD preparation | The actual `prod.prepare` restored the saved bundle into a new `drr-final-prod_prod_pg_data` volume and separate corpus/evaluation directories. All five preparation steps completed, including live search readiness; receipt retained in the isolated archive. No embeddings were generated. |
| Prepared local PROD acceptance | Unmodified `test_prepared_local_prod_has_verified_sources_vectors_and_foreign_keys` passed from the isolated source archive; `local-prod.xml`. Checks include 18 identities, 10,586 matching vectors/chunks, BM25 totals, source hashes and foreign keys. |
| Disposable Compose reset | `test_disposable_compose_reset_recreates_empty_schema` passed with the new image in 58.58 seconds; `wipe-final.xml`. The fixture owns the only volume/files it resets. |
| Wipe fixture unit checks | 19 passed, one live case deselected; `wipe-unit.xml`. Scoped Ruff/format and basedpyright passed with zero errors/warnings; `wipe-static-final.log`. |
| DEV API runtime | Real Compose + deterministic embeddings: 10 documents / 2,567 chunks, `/health`, `/ready`, `/capabilities` pass. `/retrieve` returns HTTP 200 and five actual ranked chunks; `runtime-summary.json` and `dev-retrieve.json`. |
| PROD API runtime | Real Compose + restored saved OpenAI vectors: 18 documents / 10,586 chunks, `/ready` is ready, authority readonly, local engine disabled. No query embedding or text generation was requested. |
| Actual browser | PROD: Korean preset survives Build/Back and reload, both English/Korean render, prompt settings remain readonly. DEV: edited instructions survive reload and appear in the prompt preview. Final copied DEV corpus is writable. `browser-verification.md` distinguishes UI observations from provider proof. |
| Old public evaluation detail | Actual HTTP 409 `snapshot_evidence_unavailable`; `old-snapshot-http.txt`. The saved September 9 artifacts have no current `scoring` / `evaluated_golden_sha256` fields. Restore acceptance checks integrity/counts, not current-format detail eligibility. |

All three acceptance tests use `-m live_postgres --require-live-postgres`; none is mocked or
skipped. Temporary projects use unique ports and volumes. The public artifact archive and
user DEV/PROD directories remain untouched. The runtime's selected PROD key is an explicitly
invalid local test value used only to construct the configured provider; no secret is loaded
and no provider endpoint is called. Readiness proves stored search/index state, not credential
validity or successful answer generation. DEV has no provider key or local model configured.

Initial failures are retained: the first schema setup omitted the key required by its
OpenAI identity configuration; it failed before restore and passed after the isolated
configuration was corrected. The first Docker build could not update buildx metadata in
the sandbox; the authorized build passed. The first wipe test failed on `data/runtime`
permissions: its host-owned 0755 bind mount did not match local Compose's non-root shared
group. The fixture now grants group-write on only its disposable directories, runs as
`10001:<host gid>` and uses the actual `umask 0002` command wrapper. No assertion or app
permission check changed. The initial long YAML command failed Ruff and was formatted as
a readable YAML sequence before the final checks.

The final DEV browser run uses a writable manifest-bound source copy in the disposable
archive. An earlier readonly mount correctly reported that original acquisition was not
writable; the final `/ready` confirms `writable=true`. The full-copy attempt encountered an
unreadable unrelated scratch file, so only actual manifest-listed originals were copied.
Neither condition caused an application change. The two local stacks were stopped and their
owned test volumes removed after verification; archives and logs remain for inspection.
No full Python rerun, coverage recollection, paid evaluation, real-provider answer smoke or
deployment was performed. Python application code is unchanged, so prior valid coverage and
unit evidence are retained. The new checks close the three missing acceptance environments,
not the missing historical generated text or current-format public evaluation bundle.

### Narrowing the historical decomposition decline

An additional retained run was recovered from the original scratch directory:
`/tmp/claude-1000/-home-wwaya-Documents-docreview-rag/8d36a64b-8852-4da7-a12b-0afb81f66d45/scratchpad/a2/after/evals`.
It ran at 12:38 UTC on `ec233bd6`, between baseline `7780a723` at 04:04 and final
`28f8a152` at 14:31. The intermediate/final inputs, full DB fingerprints and harness
identity `3ebb695d47d7eb92` match. All three normalized single-query arm artifacts match exactly.

| Run | `m3c-02` relevant rank | Recall / MRR | Output tokens |
| --- | --- | --- | --- |
| Baseline | 4 | 0.333333 / 0.141667 | 99 |
| Recovered intermediate | 4 | 0.333333 / 0.141667 | 70 |
| Final historical run | No hit | 0.25 / 0.120833 | 137 |

The correct source span is wholly inside chunk 2332. Earlier fused chunks are
`[2335, 12, 249, 2332, 741]`; final chunks are `[1262, 2335, 12, 1122, 249]`.
The outer fusion is byte-identical across all captured heads and current code. Its saved
scores are respectively `[1/61, 1/62, 1/63, 1/64, 1/65]` and
`[1/61, 1/61, 1/62, 1/62, 1/63]`. A shared hit would score at least `2/65`, above either
observed maximum, so these component top-fives are disjoint. Every nonempty component has
a rank-one `1/61`; with at most four subquestions and five output slots, these patterns
uniquely identify one versus two nonempty searches. The captured unrestricted vector lane
has 2,567 matching embeddings and no similarity cutoff, so successful queries cannot yield
an empty component here. This establishes a change in generated decomposition count.

Offline, with socket connections denied, the reviewer recomputed all three case scores
using `score_case` and replayed the earlier list through current fusion: all fields match.
A labeled counterfactual, the earlier list plus additional hits `[1262, 1122]`, reproduces
the final five full hits. This demonstrates the unchanged top-five truncation mechanism;
it does not reconstruct the unseen later component lists or prove where 2332 ranked in them.
The aggregate changes are exactly one lost hit among 12 positives and `0.25 / 12` lost MRR.

Between the recovered intermediate and final heads, decomposition/evaluation/scoring/fusion
are unchanged; the provider change accounts for a billed first attempt followed by a denied
repair, whereas these calls all completed in one successful request. The `responses.create`
AST remains identical,
including explicit model, input, instructions, strict schema, budgets and `store=False`.
The relevant vector branch is unchanged; BM25/reranker changes do not apply to this arm.
No code repair is justified by this evidence.

Actual generated text and per-subquestion rankings remain unavailable. The raw case objects
contain only golden/hits/latency/score; call ledgers contain usage, not output or response IDs.
The capture wrapper discarded those fields. All three temporary DB fingerprints record zero
runs/traces/eval-results, and the corresponding tmpfs containers were removed. No user DB
was searched or changed. No new paid run or provider lookup was attempted. Current per-case
decomposition recording already prevents this specific evidence gap in future runs.

## Current-format public evaluation bundle

The application source used for regeneration is main `dd82ee1535642f985236f83984f90d395ef69c5c`.
This change affects bundle validation/restoration and retired launcher defaults, not retrieval,
scoring, provider logic or DEV/PROD data authority. Existing application/Web verification
remains applicable. The new local bundle is `20260926-portfolio18`; generation scripts,
original hashes and runtime logs are retained in `/tmp/public-eval-20260926/`.

The original public dump was restored into an isolated PostgreSQL instance without its old
evaluation/snapshot table data. Current `make_retriever(provider=None, strategy="lexical")`,
`evaluate_retriever`, `persist_evaluation` and `SnapshotService.create` generated four new
records using the exact original cases, profiles and source scope. The preserved embedding
identity describes the saved vectors frozen in each snapshot; no embedding request was made.

| Published run | Cases / scored positives | Recall = hit rate | MRR |
| --- | --- | --- | --- |
| DART Korean BM25, publication 1 | 28 / 24 | 0.7083333333333334 | 0.4847222222222222 |
| DART English BM25, publication 2 | 28 / 24 | 0 | 0 |
| DART Korean BM25, publication 3 | 28 / 24 | 0.7083333333333334 | 0.4847222222222222 |
| DART Korean ts_rank_cd, publication 4 | 28 / 24 | 0.08333333333333333 | 0.049999999999999996 |

Every quality value matches the corresponding original run. English lexical recall was
already zero; it is not a newly introduced decline. Raw hit evidence and measured latency
are newly generated; neither ranking-byte equivalence nor comparable benchmark latency is
claimed. Golden case objects and their original dataset digests are unchanged. Source hashes
for the original public dump, archive and four evaluation files match their original checksums.
The private dump was never opened or copied.

The first task DB's 2GB tmpfs filled while materializing snapshot 4, after all four evaluations
and three snapshots had committed. A preserved checkpoint was restored into a 6GB task DB;
only the rolled-back snapshot creation was repeated. PostgreSQL correctly retained its sequence
gap, so snapshot IDs are 1, 2, 3 and 5. The diagnostic harness initially assumed consecutive IDs;
it was corrected to read the actual result-to-snapshot mapping. No application workaround or
score alteration resulted. Initial direct-backend local preparation lacked the required Next
proxy path; the final fixture uses the actual local PROD Compose web/API topology.

The final bundle is preserved at
`/home/wwaya/.local/share/docreview/prod-artifacts/20260926-portfolio18`.
Its `checksums.json` SHA-256 is
`8c6198da6b79b4e1f293b08435ba1bdcdd42b999163951994b6ea7baa96f0a91`;
`database.public.dump` SHA-256 is
`f59f48a5d6e3ec685d26b36b8a046f5b891b05441fc572125f4f943cb2e52888`.
The permanent copy and the tested staging bundle have identical public-file manifests.

| Verification | Final result |
| --- | --- |
| `pytest -q tests/scripts/deploy/test_gcp_backend.py tests/scripts/stack/test_prod.py -m 'not live_postgres'` | 46 passed, 1 live test deselected; corrected duplicate-key fixture was also rerun separately and passed, not counted twice |
| GCP setup/wrapper and Oracle deployment entrypoint tests with fake external commands | 10 passed; first-install blocks missing explicit artifacts before remote writes, update/rollback remain independent |
| `tests/scripts/deploy/test_01_public_restore.py -m live_postgres --require-live-postgres` against the disposable generation DB and exact bundle | 1 passed |
| `tests/scripts/stack/test_prod.py -m live_postgres --require-live-postgres` against the separate freshly prepared local PROD Compose volume | 1 passed, 15 unit cases deselected |
| Actual `prod.prepare` into empty separate Compose storage | Passed all five stages, including fresh dump restoration, references and readiness; then current-format bundle verifier passed on the permanent copy |
| Actual Next-proxied public dataset/evaluation routes for snapshot IDs 1, 2, 3, 5 | 8 HTTP 200 responses; 28 cases each, matching artifact quality metrics; `/ready` is PROD/readonly with 18 documents and 10,586 matching embeddings |
| Scoped Ruff/format, basedpyright, shell syntax and diff check | Passed; basedpyright 0 errors/warnings |
| Original old-format bundle through the current verifier | Expected rejection for missing evaluated identity; no compatibility fallback |

The final reviewer independently compared all eight captured response bodies with the
permanent bundle, checked exact case IDs, dataset digests, scores and result/snapshot links,
and reviewed the checkpoint recovery. Generation and validation scripts/logs are diagnostic
artifacts outside maintained source, not a runtime migration path. Initial failures above
remain recorded; final passes do not relabel them as successful runs.

No full Python/Web suite, coverage recollection, fresh application image build, paid call,
provider-authentication check or deployment was performed for this bounded bundle change.
The previously verified application image was reused with current unchanged Python application
source. No original bundle, user database or existing local PROD storage was replaced.
Task-owned containers/volumes were removed after verification; generated artifacts and logs
remain. The code/refactoring scope and local bundle-detail gap are complete. Live deployment
and the unrecoverable historical decomposition text are separate from that completion.
