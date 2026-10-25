# syntax=docker/dockerfile:1.7
# Backend image: Python 3.13 + uv, with the dependencies already installed.
# The source code is NOT copied in. docker-compose.yml mounts your folder at /app, so edits on your PC show up at once.
# The Python environment lives in /opt/venv (inside the image), so your Windows .venv never gets in the way.
FROM python:3.13-slim

# Bytecode is kept (not PYTHONDONTWRITEBYTECODE): without it every start recompiles ~1600 modules and takes over a minute.
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_SYNC=1 \
    PATH="/opt/venv/bin:$PATH"

# libgomp1: needed by faiss and onnxruntime. curl: used by the health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

WORKDIR /app
# Only the dependency files first: this layer is rebuilt only when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock .python-version ./
# UV_COMPILE_BYTECODE: precompile all installed packages once, here, instead of on every start.
RUN --mount=type=cache,target=/root/.cache/uv UV_COMPILE_BYTECODE=1 uv sync --frozen --no-install-project

COPY docker/backend-entrypoint.sh /usr/local/bin/entrypoint.sh
# Windows checkouts can turn line endings into CRLF, which breaks shell scripts: strip them.
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /app/support_nova_project
EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["uv", "run", "manage.py", "runserver", "0.0.0.0:8000"]
