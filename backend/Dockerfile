# ---- builder: compiles/installs dependencies into an isolated prefix ----
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- runtime: no build toolchain, non-root, healthchecked ----
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# RAW_STORAGE_DIR (see Settings) is expected to point at a mounted volume in
# production (docker-compose.yml's raw_files_data) -- pre-create and own it
# here so the non-root `app` user can write to it regardless of where it's
# mounted.
RUN mkdir -p /data/raw && chown -R app:app /app /data/raw

# sentence-transformers downloads EMBEDDING_MODEL on first use and caches it
# under HF_HOME. Without a writable location the download fails outright and
# every embedding -- and therefore all ingestion and retrieval -- breaks. Point
# it at a directory the non-root `app` user owns; mount a volume here to avoid
# re-downloading the model on every image rebuild.
ENV HF_HOME=/home/app/.cache/huggingface
RUN mkdir -p "$HF_HOME" && chown -R app:app /home/app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

USER app

# start-period covers a COLD start, not a warm restart: on first boot the app
# downloads EMBEDDING_MODEL (see app/ai/embeddings/) before it serves, which
# takes minutes on a slow link. With the old 30s grace the container was marked
# unhealthy at ~2min, and because the frontend declares
# `depends_on: backend: condition: service_healthy`, `docker compose up -d`
# exited non-zero on a fresh clone and never created the frontend at all.
# Failing probes inside start-period do not count against retries, so this is
# grace for first boot, not a weaker check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# --workers defaults to 2; override via UVICORN_WORKERS. No --reload here --
# that's a dev-only convenience, restored by docker-compose.dev.yml.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]

# ---- dev: runtime plus the test/lint toolchain, used only via
# docker-compose.dev.yml. The runtime image deliberately ships without pytest
# and ruff -- production has no business carrying them -- but the dev stack
# runs the suite inside this container, so they belong here rather than being
# pip-installed into a running container on every test run.
FROM runtime AS dev

USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER app
