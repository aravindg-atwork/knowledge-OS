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
    JWT_EXPIRE_MINUTES: int = 60 * 24
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
