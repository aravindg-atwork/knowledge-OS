from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_JWT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    ENVIRONMENT: str = "dev"
    JWT_SECRET: str = _DEV_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    # 2 hours, not 24. Access tokens are stateless and nothing revokes them:
    # a password reset does NOT end an attacker's existing session, and that
    # session also retains /auth/switch-workspace across every workspace the
    # account belongs to. Session revocation is deferred to sub-project 1b
    # (see docs/superpowers/specs/2026-08-16-tenancy-followups.md); until it
    # lands, this expiry IS the revocation window. Raise it again only once
    # real session invalidation exists.
    JWT_EXPIRE_MINUTES: int = 120
    # Only send Strict-Transport-Security when the deploy is actually behind
    # TLS (see docker-compose's Caddy edge) -- sending it over plain HTTP
    # would tell browsers to force HTTPS for a host that may not serve it.
    ENABLE_HSTS: bool = True

    # Postgres
    DATABASE_URL: str = "postgresql+psycopg://khub:khub@localhost:5432/khub"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "document_chunks"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Rate limiting (slowapi). Redis-backed -- not in-memory -- so limits are
    # enforced consistently once the backend runs as multiple uvicorn worker
    # processes (see backend/Dockerfile); an in-memory limiter would count
    # hits separately per worker and silently under-enforce.
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_CHAT: str = "30/minute"
    RATE_LIMIT_REDIS_URL: str = "redis://localhost:6379/2"

    # AI provider
    AI_PROVIDER: str = "local"  # local | mistral | openai | anthropic (future)
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "llama3.2:1b"
    MISTRAL_API_KEY: str = ""
    MISTRAL_MODEL: str = "mistral-small-latest"

    # Email -- console prints to logs so local dev needs no credentials.
    EMAIL_PROVIDER: str = "console"  # console | resend
    RESEND_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "no-reply@localhost"
    # Base URL the emailed links point at (the frontend, not the API).
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    RATE_LIMIT_SIGNUP: str = "5/hour"
    RATE_LIMIT_INVITE: str = "30/hour"
    RATE_LIMIT_INVITE_PREVIEW: str = "20/minute"
    RATE_LIMIT_PASSWORD_RESET: str = "5/hour"

    # Connectors
    GOOGLE_DRIVE_MODE: str = "mock"  # mock | real

    # Google OAuth (shared by the Drive and Gmail connectors in "real" mode).
    # Create these in Google Cloud Console -> APIs & Services -> Credentials
    # (OAuth client ID, type "Web application") after enabling the Drive and
    # Gmail APIs for the project. GOOGLE_OAUTH_REDIRECT_URI must be added
    # there verbatim as an "Authorized redirect URI".
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8010/api/v1/connectors/google/oauth/callback"

    # Document storage
    RAW_STORAGE_DIR: str = "./data/raw"
    DOCUMENT_CONTENT_MODE: str = "cached"  # cached | redirect

    # CORS: comma-separated list of allowed browser origins
    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173"

    @property
    def allowed_origins(self) -> list[str]:
        origins = self.CORS_ALLOWED_ORIGINS.split(",")
        return [origin.strip() for origin in origins if origin.strip()]

    @model_validator(mode="after")
    def _validate_prod_secrets(self) -> "Settings":
        """Refuse to boot with the shipped dev JWT secret outside local dev.

        Catches the "forgot to set JWT_SECRET before deploying" mistake at
        process startup instead of letting it run silently -- a leaked/
        guessable secret lets anyone forge a valid session token.
        """
        if self.ENVIRONMENT != "dev":
            if self.JWT_SECRET == _DEV_JWT_SECRET:
                raise ValueError(
                    "JWT_SECRET is still the default dev value. Set a real secret "
                    "(e.g. `openssl rand -hex 32`) via the JWT_SECRET env var before "
                    "running with ENVIRONMENT != 'dev'."
                )
            if len(self.JWT_SECRET) < 32:
                raise ValueError(
                    f"JWT_SECRET must be at least 32 characters outside dev "
                    f"(got {len(self.JWT_SECRET)}). Generate one with "
                    f"`openssl rand -hex 32`."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
