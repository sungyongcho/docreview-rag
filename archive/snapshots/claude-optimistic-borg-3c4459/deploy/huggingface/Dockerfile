FROM node:24-alpine AS web

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
ENV NEXT_PUBLIC_API_BASE_URL=/docreview-rag-agent/api \
	NEXT_PUBLIC_ADMIN_MODE=canned
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV HOME=/home/user \
	PATH=/home/user/.local/bin:$PATH \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	UV_COMPILE_BYTECODE=1 \
	UV_LINK_MODE=copy \
	DOCREVIEW_MODE=canned \
	DOCREVIEW_ADMIN_MODE=readonly \
	DOCREVIEW_PORT=7860

RUN useradd --create-home --uid 1000 user \
	&& mkdir --parents /home/user/app \
	&& chown user:user /home/user/app
WORKDIR /home/user/app

COPY --from=uv /uv /uvx /bin/
COPY --chown=user:user pyproject.toml uv.lock ./

USER user
RUN uv sync --locked --no-dev --no-install-project

COPY --chown=user:user app ./app
COPY --from=web --chown=user:user /web/out ./web/out

EXPOSE 7860

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
	CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "uvicorn", "app.release.space:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--log-level", "warning"]
