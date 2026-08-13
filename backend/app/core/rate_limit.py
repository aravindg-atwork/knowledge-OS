from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

# Module-level singleton, per slowapi's expected usage: route decorators
# (`@limiter.limit(...)`) reference this same instance, and `main.py` wires
# it into the FastAPI app once at startup. Redis-backed (see Settings docs)
# so it's safe under multiple worker processes.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=get_settings().RATE_LIMIT_REDIS_URL,
)
