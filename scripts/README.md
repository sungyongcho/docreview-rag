# Script packages

Run Python modules from the repository root after `uv sync --locked`. Registered `rag-*` helpers
select their own checkout from any directory. There are no compatibility modules or re-export
packages. Schema preparation lives in `scripts.schema.status`; Quick Start calls that shared code.

| Package | Entry points and ownership |
|---|---|
| `schema` | `python -m scripts.schema check\|prepare\|recover\|recreate`; `status.py` owns inspection/preparation, `recovery.py` isolated recovery, `recreate.py` confirmed recreation, `sources.py` source journals |
| `stack` | `python -m scripts.stack dev\|prod [COMPOSE_ARGS...]`; `environment.py` validates bindings, `operator.py` manages host Operations, `commands.py` implements `fresh-start` and `corpus` |
| `stack` setup | `bash scripts/stack/quickstart.sh` bootstraps the locked Python environment then runs `scripts.stack.quickstart`; `scripts/stack/operator_web.sh` configures the SSH-tunnel web UI |
| `diagnostics` | `python -m scripts.diagnostics.ollama` checks model connectivity; `python -m scripts.diagnostics.readiness` measures health/readiness during ingestion; `python -m scripts.diagnostics.local_grade` runs the explicit local-model benchmark |
| `release` | `python -m scripts.release.api_schema [--check]`, `python -m scripts.release.web_build`, `python -m scripts.release.container_startup IMAGE PORT`, `bash scripts/release/clean_checkout.sh` |
| `deploy` | `FIREBASE_PROJECT_ID=<project-id> scripts/deploy/firebase.sh` builds, stages and publishes Firebase Hosting in one command |

Shell remains only for dependency bootstrap, the SSH web environment, release orchestration and
Firebase deployment. The shell helper invokes Python modules directly. Tests follow these groups
under `tests/scripts/`; helper registration tests remain in `tests/scripts/test_rag_alias.py`.

The readiness measurement logic and G10 deferral from [PR #101](https://github.com/sungyongcho/docreview-rag-agent/pull/101)
are unchanged. Its two-filing, 1,548-chunk run measured BM25-stage readiness p95/max at 4.3 ms after
the G9 fix. This is evidence for that workload, not a larger-corpus performance claim. Measure a
specific larger workload before changing the transactional BM25 rebuild.

The clean-checkout gate installs locked dependencies in a disposable archive, runs release/API and
web checks, builds both images and checks canned health. Run host checks under a two-core affinity
and select a dedicated two-core Docker builder using `BUILDX_BUILDER`; Docker daemon builds do not
inherit host affinity. `DOCREVIEW_VERIFY_CPUSET` selects the two smoke-container CPUs (default `0-1`).
Use only isolated DB fixtures for live PostgreSQL tests; never point them at a user's database.
Deployment and destructive schema commands retain their explicit authorization requirements.
