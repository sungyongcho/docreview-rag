.PHONY: install run debug clean lint typecheck test setup next docs quality

M1_TESTS := tests/ingestion/test_01_blocks.py \
	tests/ingestion/test_02_rules.py \
	tests/ingestion/test_03_segment.py \
	tests/ingestion/test_04_validate.py \
	tests/ingestion/test_05_profile.py \
	tests/ingestion/test_06_xref.py \
	tests/ingestion/test_07_coverage.py \
	tests/ingestion/test_08_items.py

install: setup

setup:
	uv sync --locked --group dev

run:
	uv run python -m app.ingestion.parser --coverage

debug:
	uv run pytest -o addopts="" $(M1_TESTS) -vv --tb=long

next:
	uv run python scripts/next_milestone.py

clean:
	find app tests scripts -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache

lint:
	uv run ruff check --no-fix app tests scripts
	uv run ruff format --check app tests scripts

docs:
	uv run pytest -o addopts="" tests/test_doc_format.py -q

typecheck:
	uv run --with basedpyright basedpyright app tests scripts

test:
	uv run pytest

quality: lint typecheck docs test
	git diff --check
