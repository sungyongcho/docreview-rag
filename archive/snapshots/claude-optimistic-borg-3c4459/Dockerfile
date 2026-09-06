FROM node:24-alpine AS web

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
ARG NEXT_PUBLIC_API_BASE_URL=/docreview-rag-agent/api
ARG NEXT_PUBLIC_ADMIN_MODE=canned
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
	NEXT_PUBLIC_ADMIN_MODE=${NEXT_PUBLIC_ADMIN_MODE}
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	UV_COMPILE_BYTECODE=1 \
	UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser data ./data
COPY --chown=appuser:appuser app ./app
COPY --from=web --chown=appuser:appuser /web/out ./web/out

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
	CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "uvicorn", "app.release.space:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "warning"]
