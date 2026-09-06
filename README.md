# DocReview RAG Agent — Zero Learning Branch

This branch rebuilds the project by hand, milestone by milestone, following the bilingual tutorials. The completed implementation remains on `new`.

Documentation starts at the [project documentation hub](docs/00-README.md). How the repository is operated — branch and import model, change recipes, the documentation machinery, and the checkpoint checklist — is documented in the [operations handbook](docs/project/handbook.md).

## Branch roles

| Branch | Purpose |
|---|---|
| `zero` | Learn by creating the canonical implementation files yourself |
| `new` | Completed reference source used by the documentation checker and portfolio comparison |

Ordinary learning does not require switching branches because every build tutorial contains the complete canonical files. Commit or stash local work before switching when you intentionally want to inspect the completed project.

```bash
git status --short
git switch new
git switch zero
```

## What the branch retains

- every English and Korean tutorial, including complete future code blocks;
- future test harnesses, golden fixtures, corpus inputs, and reference measurements;
- uv, Docker, deployment, documentation, and repository configuration;
- no learner-suffix implementation files; every module uses its canonical path.

Future tests and assets are inputs for later milestones. Their presence does not mean those milestones are complete.

## Current progress

Progress lives in exactly two places and nowhere else: the machine-readable state in [`docs/project/learning.toml`](docs/project/learning.toml) and the human view in the Status column of [`docs/project/module-plan.md`](docs/project/module-plan.md).

## Verify the environment

```bash
uv sync --locked --group dev
uv run pytest
make docs
```

Raw SEC HTML and the 42 curriculum PDFs are intentionally ignored by Git, so they remain local when switching between `new` and `zero`.

## Start the next milestone

- Check the next checkpoint in [`docs/project/module-plan.md`](docs/project/module-plan.md) and open its linked tutorial.
- Create the canonical file directly at its documented path. Do not create a learner-suffix copy.
- Implement segment by segment in tutorial order, running the focused gate after each segment:

```bash
make next
```

The complete branch workflow is documented in [`docs/project/handbook.md`](docs/project/handbook.md); the code quality and tutorial authoring contracts are in [`docs/project/learning-baseline.md`](docs/project/learning-baseline.md).
