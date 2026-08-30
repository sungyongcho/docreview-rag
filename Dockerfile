FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	UV_COMPILE_BYTECODE=1 \
	UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
# README.md stays out of this layer on purpose: with --no-install-project the project
# metadata is never built, and the README churns with almost every commit — copying it
# here would invalidate the dependency install on each edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

RUN useradd --create-home --uid 10001 appuser
# The corpus layer changes rarely; ordering it before app/ keeps code edits from
# rewriting the largest layer. .dockerignore keeps eval artifacts out of it.
COPY --chown=appuser:appuser data ./data
COPY --chown=appuser:appuser app ./app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
	CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "python", "-m", "app.cli", "serve", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
