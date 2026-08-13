# Enterprise Knowledge Hub AI

Milestone 1: a vertical slice proving the core architecture — a mocked Google Drive
connector synced through a document pipeline (extract → chunk → embed) into a
permission-aware RAG chat that cites and can open the original source document.

Runs fully local: FastAPI + PostgreSQL + Qdrant + Redis/Celery + Ollama (local LLM)
+ sentence-transformers (local embeddings). No cloud AI APIs, no real OAuth yet —
the Google Drive connector is mocked behind the same interface a real one will use.

## Running locally

```
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

(`docker-compose.yml` alone is the hardened production shape -- see
[`docs/PRODUCTION.md`](docs/PRODUCTION.md); `docker-compose.dev.yml` layers
back bind mounts, `--reload`, and published debug ports for local iteration.)

- Frontend: http://localhost:5173
- Backend API: http://localhost:8010 (docs at /docs, health at /health)
- Qdrant dashboard: http://localhost:6333/dashboard
- Ollama: http://localhost:11434

## Backend tests

```
cd backend
pip install -r requirements-dev.txt
pytest
```

## Architecture

See the connector framework (`backend/app/connectors/`), document pipeline
(`backend/app/pipeline/`, `backend/app/workers/`), AI provider abstraction
(`backend/app/ai/`), and RAG services (`backend/app/services/`) for the
swappable seams: mock connector → real Google Drive API, local models → cloud
LLM/embedding providers.

## Production deployment

This repo ships as a local-only Milestone 1 vertical slice. See
[`docs/PRODUCTION.md`](docs/PRODUCTION.md) for the environment variables and
hardening steps required to run it with `ENVIRONMENT` set to anything other
than `dev`.


Found something worth flagging: while verifying item 10 against a real service stack, the full test suite failed intermittently (~1 in 3 runs) with a Qdrant 409 Conflict on create_collection — a pre-existing TOCTOU race in ensure_collection's check-then-create pattern, unrelated to anything in my plan. It's not something I was asked to fix, but it directly undermines the CI job I'm building (a flaky test makes the pass/fail signal worthless). Let me show you the exact code and the fix before touching it.

  Read 1 file
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 ☐ Qdrant race fix

This is outside the approved 11-item plan (it's app/pipeline code, not infra hardening). Want me to fix the race now since it'll make the new CI flaky, or just note it and leave it alone?

❯ 1. Fix it now (Recommended)
     Small, contained fix in ensure_collection() -- catch the 409/"already exists" response and treat it as success instead of raising. Makes the CI job in item 10 actually reliable.
  2. Just note it, don't touch app code
     Leave qdrant_store.py untouched. I'll document the flake risk in the CI workflow/plan and move on -- you can address it separately later.
  3. Type something.
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  4. Chat about this

Enter to select · ↑/↓ to navigate · Esc to cancel

  11 tasks (9 done, 1 in progress, 1 open)
  ◼ 10. CI pipeline
  ◻ 11. Close load-bearing test gaps
  ✔ 1. Secrets/config hardening
  ✔ 2. Structured logging + request correlation IDs
  ✔ 3. Global exception handler + security headers
   … +6 completed