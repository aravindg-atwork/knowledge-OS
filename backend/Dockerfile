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
    && groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# RAW_STORAGE_DIR (see Settings) is expected to point at a mounted volume in
# production (docker-compose.yml's raw_files_data) -- pre-create and own it
# here so the non-root `app` user can write to it regardless of where it's
# mounted.
RUN mkdir -p /data/raw && chown -R app:app /app /data/raw

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# --workers defaults to 2; override via UVICORN_WORKERS. No --reload here --
# that's a dev-only convenience, restored by docker-compose.dev.yml.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
