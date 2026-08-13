# Production deployment notes

This doc tracks what's required to run Enterprise Knowledge Hub AI with
`ENVIRONMENT` set to anything other than `dev`. It grows alongside the
production-hardening work — each item below was added by the change that
introduced the requirement.

## Required environment variables

| Variable | Requirement | Why |
|---|---|---|
| `ENVIRONMENT` | Set to `production` (or any non-`dev` value) | Gates the checks below and disables dev-only leniency (e.g. exception detail in responses, once added). |
| `JWT_SECRET` | At least 32 characters, must not be the shipped dev default (`dev-secret-change-me` / `change-me-in-real-deployments`) | Signs session JWTs. A short or default secret lets anyone forge a valid login. Generate one with `openssl rand -hex 32`. The app refuses to start without a valid one when `ENVIRONMENT != dev`. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of the real browser origin(s) your frontend is served from (e.g. `https://khub.example.com`) | The API rejects cross-origin browser requests from anywhere not on this list. Defaults to the local Vite dev origin (`http://localhost:5173`), which is wrong for a real deployment. |
| `RATE_LIMIT_REDIS_URL` | A reachable Redis instance/DB index, distinct from the Celery broker/result-backend DB indices | Backs `/auth/login` and `/chat` rate limiting (`RATE_LIMIT_LOGIN`, `RATE_LIMIT_CHAT`). Must be Redis (not in-memory) once the backend runs multiple uvicorn workers, or limits are under-enforced. |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Real, non-default credentials | Read by `docker-compose.yml` itself (not the app) to template the `postgres` container and the `DATABASE_URL` passed into `backend`/`celery_worker`/`celery_beat`. Defaults to `khub`/`khub`/`khub`, which is fine for local dev only. |
| `DOMAIN` | Your real public domain (e.g. `khub.example.com`), or omit for `localhost` | Passed to the frontend's Caddy container. With a real domain and 80/443 reachable from the internet, Caddy automatically obtains a Let's Encrypt certificate; left as `localhost` it self-signs instead. |

## Running in production shape

```
docker compose up -d --build
```

(the base `docker-compose.yml` alone -- no `-f docker-compose.dev.yml`). This
runs every service with no bind mounts, no `--reload`, restart policies, and
resource limits, and publishes only the frontend's Caddy container (80/443)
to the host -- `postgres`/`redis`/`qdrant`/`ollama`/`backend` are reachable
only from other containers on the compose network. For local development,
use `docker compose -f docker-compose.yml -f docker-compose.dev.yml up
--build` instead, which adds back bind mounts, `--reload`, and the
individual services' debug ports.

## Generating a secret

```
openssl rand -hex 32
```

Put the result in `JWT_SECRET` in your deployment's `.env` (or secret store —
do not commit it). Do not reuse the same secret across environments
(dev/staging/prod).

## Verifying the fail-fast check

```
cd backend
ENVIRONMENT=production JWT_SECRET=dev-secret-change-me python -c "from app.core.config import Settings; Settings()"
```

This should raise a `ValidationError` immediately. With a real secret
(`ENVIRONMENT=production JWT_SECRET=$(openssl rand -hex 32) python -c "..."`)
it should succeed silently.

<!-- Later items in the production-hardening plan append their own
     required-env-var rows and sections here (CORS origins, rate-limit
     Redis URL, TLS domain, Postgres credentials, etc.). -->
