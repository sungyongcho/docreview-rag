.PHONY: install run debug clean lint test setup demo demo-check docs quality

DOC_TARGETS := README.md docs deploy/huggingface/README.md

install: setup

run: demo

debug:
	uv run pytest -o addopts="" tests/demo -vv --tb=long

clean:
	find app tests scripts -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache

lint:
	uv run ruff check --no-fix app tests scripts

setup:
	uv sync --locked --extra demo

demo:
	uv run --extra demo python -m app.demo

demo-check:
	uv run pytest -o addopts="" tests/demo -q
	uv run --extra demo python -c "from app.demo import build_demo; demo = build_demo(); _, local_url, _ = demo.launch(server_name='127.0.0.1', server_port=7861, prevent_thread_lock=True, quiet=True); print(local_url); demo.close()"

docs:
	uv run python scripts/check_doc_code.py $(DOC_TARGETS)
	uv run python scripts/check_doc_parity.py inventory
	uv run python scripts/check_doc_parity.py parity
	uv run python scripts/check_doc_parity.py language
	uv run python scripts/format_docs.py --check docs
	uv run python scripts/sync_tutorial_code.py --check
	uv run pytest -o addopts="" tests/test_doc_sync.py tests/test_doc_parity.py tests/test_doc_format.py -q

test:
	uv run pytest -o addopts="" -q

quality:
	$(MAKE) lint
	uv run python scripts/check_doc_code.py $(DOC_TARGETS)
	uv run python scripts/check_doc_parity.py inventory
	uv run python scripts/check_doc_parity.py parity
	uv run python scripts/check_doc_parity.py language
	uv run pytest -o addopts="" tests/test_doc_sync.py tests/test_doc_parity.py -q
	git diff --check
