# syntax=docker/dockerfile:1.7
ARG NODE_IMAGE=node:22.23.3-bookworm-slim
ARG PYTHON_IMAGE=python:3.13.15-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.21

FROM ${NODE_IMAGE} AS web-build
WORKDIR /src
ENV COREPACK_HOME=/tmp/corepack
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN corepack enable && corepack prepare pnpm@12.8.1 --activate \
    && pnpm install --frozen-lockfile --filter @ares/web...
COPY apps/web apps/web
RUN pnpm --filter @ares/web typecheck \
    && pnpm --filter @ares/web test \
    && pnpm --filter @ares/web build

FROM ${UV_IMAGE} AS uv-bin

FROM ${PYTHON_IMAGE} AS backend-build
COPY --from=uv-bin /uv /uvx /bin/
WORKDIR /src
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY backend/pyproject.toml backend/uv.lock backend/
RUN uv sync --project backend --frozen --no-dev --no-install-project
COPY backend backend
RUN uv sync --project backend --frozen --no-dev

# M08 heavy local parsing/OCR/embedding dependencies live in a separate image target.
# Model artifacts must be provisioned explicitly; request handling never downloads models.
FROM backend-build AS backend-build-media
COPY backend/requirements-media.txt /tmp/requirements-media.txt
RUN uv pip install --python /src/backend/.venv/bin/python --requirement /tmp/requirements-media.txt

FROM ${PYTHON_IMAGE} AS runtime-base
ARG APP_UID=10001
ARG APP_GID=10001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/backend/.venv/bin:$PATH \
    PYTHONPATH=/app/backend/src \
    WEB_DIST_DIR=/app/web-dist \
    BLOB_ROOT=/app/data/blobs \
    WORKER_HEALTH_FILE=/app/data/worker-health
RUN groupadd --gid ${APP_GID} ares \
    && useradd --uid ${APP_UID} --gid ${APP_GID} --create-home --shell /usr/sbin/nologin ares \
    && mkdir -p /app/data /app/web-dist \
    && chown -R ares:ares /app
WORKDIR /app
COPY --from=web-build --chown=ares:ares /src/apps/web/dist web-dist
COPY --chown=ares:ares scripts scripts
USER ares:ares
STOPSIGNAL SIGTERM

FROM runtime-base AS runtime
COPY --from=backend-build --chown=ares:ares /src/backend backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()" || exit 1
CMD ["uvicorn", "ares.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]

FROM runtime-base AS runtime-media
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=backend-build-media --chown=ares:ares /src/backend backend
USER ares:ares
ENV WORKER_PROFILE=media
CMD ["python", "-m", "ares.worker.main"]
