from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.core.rate_limit import limiter


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.ENVIRONMENT)
    app = FastAPI(title="Enterprise Knowledge Hub AI", version="0.1.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    # Starlette makes the most-recently-added middleware outermost, so this
    # list runs (for an incoming request) CORS -> SlowAPI -> RequestId ->
    # SecurityHeaders -> route handler. CORS is outermost so its preflight
    # short-circuit and response headers apply uniformly, including to
    # rate-limited (429) and error responses. SlowAPIMiddleware only touches
    # Redis for routes carrying an explicit `@limiter.limit(...)` decorator;
    # every other route (e.g. /health) passes through untouched.
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=settings.ENABLE_HSTS)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app, environment=settings.ENVIRONMENT)
    app.include_router(api_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
