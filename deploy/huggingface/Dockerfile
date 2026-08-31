FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV HOME=/home/user \
	PATH=/home/user/.local/bin:$PATH \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	UV_COMPILE_BYTECODE=1 \
	UV_LINK_MODE=copy \
	DOCREVIEW_MODE=canned \
	DOCREVIEW_PORT=7860

RUN useradd --create-home --uid 1000 user \
	&& mkdir --parents /home/user/app \
	&& chown user:user /home/user/app
WORKDIR /home/user/app

COPY --from=uv /uv /uvx /bin/
COPY --chown=user:user pyproject.toml uv.lock README.md ./

USER user
RUN uv sync --locked --no-dev --extra demo --no-install-project

COPY --chown=user:user app ./app

EXPOSE 7860

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
	CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "uvicorn", "app.release.space:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--log-level", "warning"]
